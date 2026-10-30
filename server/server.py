# npm start
import uvicorn
import json
import os
import re
import logging
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.types.steam import KeyStatus, Settings, SettingsUpdate, ResolvedSteamUser, DealsResult, Me
from src.steam_api import Steam
from src.dealsgg_api import DealsGGAPI
from src.http_client import get_client
from src import auth, crypto, db, deals_service, discord_app

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Local development reads server/.env; on Vercel the variables come from the project settings
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

STEAM_ID_RE = re.compile(r'\d{17}')
# Requests that change data must come from our own pages. Discord signs its requests instead.
CSRF_EXEMPT_PREFIXES = ('/api/discord/',)

app = FastAPI()


@app.middleware('http')
async def csrf_protect(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not request.url.path.startswith(CSRF_EXEMPT_PREFIXES):
        origin = request.headers.get('origin', '')
        expected = urlsplit(auth.base_url(request))
        if urlsplit(origin)[:2] != expected[:2]:
            return JSONResponse({'detail': 'Request blocked: it did not come from this site.'}, status_code=403)
        if not request.headers.get('content-type', '').startswith('application/json'):
            return JSONResponse({'detail': 'Requests must be JSON.'}, status_code=415)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


# ---- Sign in with Steam ----

@app.get('/api/auth/steam/login')
async def steam_login(request: Request, link: str = ''):
    # `link` is a Discord link code from the /link command
    state = auth.make_state(link[:64])
    nonce = auth.read_state(state)['n']
    response = RedirectResponse(auth.login_redirect_url(request, nonce), status_code=302)
    auth.set_cookie(response, request, auth.STATE_COOKIE, state, auth.STATE_MINUTES * 60)
    return response


@app.get('/api/auth/steam/callback')
async def steam_callback(request: Request):
    base = auth.base_url(request)
    state = auth.read_state(request.cookies.get(auth.STATE_COOKIE))

    def finish(query: str, steam_id: str | None = None):
        response = RedirectResponse(f'{base}/?{query}', status_code=302)
        response.delete_cookie(auth.STATE_COOKIE, path='/')
        if steam_id:
            auth.set_cookie(response, request, auth.SESSION_COOKIE, auth.make_session(steam_id), auth.SESSION_DAYS * 86400)
        return response

    if state is None:
        return finish(urlencode({'login_error': 'Sign-in expired. Try again.'}))

    try:
        steam_id = await auth.verify_login(get_client(), dict(request.query_params), base, state['n'])
    except auth.LoginError as error:
        return finish(urlencode({'login_error': str(error)}))

    persona_name, avatar_url = await auth.public_profile(get_client(), steam_id)
    await db.upsert_user(steam_id, persona_name, avatar_url)
    logger.info('User signed in.')

    if state.get('link'):
        linked = await db.redeem_link_code(state['link'], steam_id)
        return finish('discord=' + ('linked' if linked else 'link_expired'), steam_id)
    return finish('signed_in=1', steam_id)


@app.get('/api/auth/me')
async def me(steam_id: str = Depends(auth.require_user)) -> Me:
    user = await db.get_user(steam_id)
    if user is None:
        raise HTTPException(status_code=401, detail='Sign in with Steam first.')
    return Me(steam_id=steam_id, persona_name=user.persona_name or steam_id,
              avatar_url=user.avatar_url, discord_linked=bool(user.discord_user_id))


@app.post('/api/auth/logout')
async def logout():
    response = JSONResponse({'ok': True})
    response.delete_cookie(auth.SESSION_COOKIE, path='/')
    return response


# ---- Per-user settings ----

def key_status(key: str) -> KeyStatus:
    return KeyStatus(is_set=bool(key), hint=crypto.hint(key))


async def current_settings(steam_id: str) -> Settings:
    keys = await db.get_keys(steam_id)
    user = await db.get_user(steam_id)
    return Settings(
        steam_api_key=key_status(keys['steam_api_key']),
        deals_api_key=key_status(keys['deals_api_key']),
        discord_linked=bool(user and user.discord_user_id),
    )


async def user_clients(steam_id: str) -> tuple[Steam, DealsGGAPI]:
    keys = await db.get_keys(steam_id)
    return Steam(keys['steam_api_key']), DealsGGAPI(keys['deals_api_key'])


def require_key(key: str, name: str):
    if not key:
        raise HTTPException(status_code=400, detail=f'Add your {name} API key on the Settings page first.')


@app.get('/api/settings')
async def get_settings(steam_id: str = Depends(auth.require_user)) -> Settings:
    return await current_settings(steam_id)


@app.put('/api/settings')
async def update_settings(update: SettingsUpdate, steam_id: str = Depends(auth.require_user)) -> Settings:
    steam_key = (update.steam_api_key or '').strip()
    deals_key = (update.deals_api_key or '').strip()
    remove = set(update.remove or [])

    # Check everything before saving anything
    if steam_key and not await Steam().check_api_key(steam_key):
        raise HTTPException(status_code=400, detail='Steam rejected that API key.')
    if deals_key and not await DealsGGAPI().check_api_key(deals_key):
        raise HTTPException(status_code=400, detail='GG.deals rejected that API key.')

    await db.set_keys(
        steam_id,
        steam_api_key=steam_key or ('' if 'steam_api_key' in remove else None),
        deals_api_key=deals_key or ('' if 'deals_api_key' in remove else None),
    )
    logger.info('Settings updated.')
    return await current_settings(steam_id)


# ---- Steam lookups and deals ----

@app.get('/api/steam/resolve')
async def resolve_steam_id(query: str, steam_id: str = Depends(auth.require_user)) -> ResolvedSteamUser:
    steam, _ = await user_clients(steam_id)
    require_key(steam.steam_api_key, 'Steam')
    not_found = 'No Steam account matches that. Check the spelling or paste your full profile URL.'
    try:
        found_id = await steam.resolve_steam_id(query)
        if not found_id:
            raise HTTPException(status_code=404, detail=not_found)

        player = await steam.get_user_account(found_id)
        try:
            wishlist_count = len(await steam.get_wishlist(found_id))
        except (ValueError, KeyError):
            # Steam returns no items for an empty or private wishlist
            wishlist_count = 0

        return ResolvedSteamUser(
            steamid=found_id,
            persona_name=player['persona_name'],
            profile_url=player['profile_url'],
            avatar_full=player['avatar_full'],
            wishlist_count=wishlist_count
        )
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=not_found)
    except Exception as error:
        logger.error(f'Steam API Error: {type(error).__name__}')
        raise HTTPException(status_code=500, detail='Error fetching data from Steam API')


@app.get('/api/deals/{kind}/{target_id}')
async def get_deals(
    kind: Literal['wishlist', 'library'],
    target_id: str,
    max_price: float = Query(deals_service.DEFAULT_MAX_PRICE, gt=0, le=1000),
    sort: Literal['found', 'price', 'discount', 'name'] = 'found',
    steam_id: str = Depends(auth.require_user),
) -> DealsResult:
    if not STEAM_ID_RE.fullmatch(target_id):
        raise HTTPException(status_code=400, detail='Steam ID must be the 17-digit SteamID64.')
    steam, dealsgg = await user_clients(steam_id)
    require_key(dealsgg.api_key, 'GG.deals')
    # Public wishlists work without a Steam key; libraries need one
    if kind == 'library':
        require_key(steam.steam_api_key, 'Steam')

    try:
        return await deals_service.scan(kind, target_id, steam, dealsgg, max_price, sort)
    except deals_service.RateLimited:
        raise HTTPException(status_code=429, detail='GG.deals is rate limiting requests. Try again in a minute.')
    except ValueError:
        raise HTTPException(status_code=404, detail=f'No {kind} found. It may be empty or private.')
    except httpx.HTTPError as error:
        logger.error(f'Deals scan failed: {type(error).__name__}')
        raise HTTPException(status_code=502, detail='Steam or GG.deals did not answer. Try again.')


# ---- Discord ----

async def start_discord_work(base: str, work: dict):
    """
        Starts the scan as its own request and returns without waiting for it, so Discord gets
        its deferred reply within 3 seconds. Vercel's Python runtime has no way to keep working
        after a response is sent, so the work runs in a second function call.
    """
    try:
        await get_client().post(f'{base}/api/discord/work', json=work,
                                headers={'X-Work-Secret': discord_app.work_secret()},
                                timeout=httpx.Timeout(1.5, connect=1.0))
    except httpx.ReadTimeout:
        pass  # Expected: the work request was sent and keeps running
    except httpx.HTTPError as error:
        logger.error(f'Could not start Discord work: {type(error).__name__}')


@app.post('/api/discord/interactions')
async def discord_interactions(request: Request):
    public_key = os.getenv('DISCORD_PUBLIC_KEY', '')
    body = await request.body()
    if not public_key or not discord_app.verify_signature(
        public_key,
        request.headers.get('x-signature-ed25519', ''),
        request.headers.get('x-signature-timestamp', ''),
        body,
    ):
        return JSONResponse({'detail': 'invalid request signature'}, status_code=401)

    interaction = json.loads(body)
    base = auth.base_url(request)
    kind = interaction.get('type')
    if kind == discord_app.PING:
        return {'type': discord_app.PONG}
    if kind == discord_app.APPLICATION_COMMAND:
        reply, work = await discord_app.handle_command(interaction, base)
        if work:
            await start_discord_work(base, work)
        return reply
    if kind == discord_app.MESSAGE_COMPONENT:
        return await discord_app.handle_component(interaction, base)
    return JSONResponse({'detail': 'unsupported interaction'}, status_code=400)


@app.post('/api/discord/work')
async def discord_work(request: Request):
    if not discord_app.check_work_secret(request.headers.get('x-work-secret', '')):
        return JSONResponse({'detail': 'forbidden'}, status_code=403)
    await discord_app.do_work(await request.json(), auth.base_url(request), get_client())
    return {'ok': True}


if __name__ == '__main__':
    PORT = int(os.getenv('PORT', 5000))
    logger.info(f'Server at http://localhost:{PORT}')
    # uvicorn.run("server:app", host='0.0.0.0', port=PORT, reload=True)
    uvicorn.run("server:app", host='0.0.0.0', port=PORT)
