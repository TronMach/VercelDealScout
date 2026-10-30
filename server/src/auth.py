"""
    Sign in with Steam (OpenID 2.0) and signed session cookies.

    Flow: /api/auth/steam/login sends the browser to Steam. Steam sends it back to
    /api/auth/steam/callback with a signed assertion, which we confirm by posting it back
    to Steam with openid.mode=check_authentication.
"""
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

STEAM_OPENID_URL = 'https://steamcommunity.com/openid/login'
OPENID_NS = 'http://specs.openid.net/auth/2.0'
IDENTIFIER_SELECT = 'http://specs.openid.net/auth/2.0/identifier_select'
CLAIMED_ID_RE = re.compile(r'^https://steamcommunity\.com/openid/id/(\d{17})$')
CALLBACK_PATH = '/api/auth/steam/callback'

SESSION_COOKIE = 'ds_session'
STATE_COOKIE = 'ds_login_state'
SESSION_DAYS = 30
STATE_MINUTES = 10


class LoginError(Exception):
    """ The Steam login could not be verified. The message is safe to show. """


def base_url(request: Request) -> str:
    """
        The public address of the app, with no trailing slash.
        Set APP_BASE_URL in production. Locally the Vite dev server (port 5173) proxies /api here.
    """
    configured = os.getenv('APP_BASE_URL', '').rstrip('/')
    if configured:
        return configured
    if os.getenv('VERCEL'):
        host = request.headers.get('x-forwarded-host') or request.headers.get('host', '')
        return f'https://{host}'
    return 'http://localhost:5173'


def is_secure(request: Request) -> bool:
    return base_url(request).startswith('https://')


def _serializer(salt: str) -> URLSafeTimedSerializer:
    secret = os.getenv('SESSION_SECRET')
    if not secret:
        raise RuntimeError('SESSION_SECRET is not set.')
    return URLSafeTimedSerializer(secret, salt=salt)


# ---- Sessions ----

def make_session(steam_id: str) -> str:
    return _serializer('session').dumps({'sid': steam_id})


def read_session(token: str | None) -> str | None:
    """ Return: the signed-in SteamID64, or None. """
    if not token:
        return None
    try:
        data = _serializer('session').loads(token, max_age=SESSION_DAYS * 86400)
    except BadSignature:
        return None
    steam_id = data.get('sid') if isinstance(data, dict) else None
    return steam_id if isinstance(steam_id, str) and re.fullmatch(r'\d{17}', steam_id) else None


def current_steam_id(request: Request) -> str | None:
    return read_session(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request) -> str:
    """ FastAPI dependency: the signed-in SteamID64, or 401. """
    steam_id = current_steam_id(request)
    if not steam_id:
        raise HTTPException(status_code=401, detail='Sign in with Steam first.')
    return steam_id


def set_cookie(response, request: Request, name: str, value: str, max_age: int):
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=is_secure(request),
                        samesite='lax', path='/')


# ---- Login ----

def make_state(link_code: str = '') -> str:
    """ A signed value kept in a cookie during login, so only the browser that started a login can finish it. """
    return _serializer('login-state').dumps({'n': secrets.token_urlsafe(16), 'link': link_code})


def read_state(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return _serializer('login-state').loads(token, max_age=STATE_MINUTES * 60)
    except BadSignature:
        return None


def login_redirect_url(request: Request, state_nonce: str) -> str:
    base = base_url(request)
    params = {
        'openid.ns': OPENID_NS,
        'openid.mode': 'checkid_setup',
        'openid.return_to': f'{base}{CALLBACK_PATH}?{urlencode({"state": state_nonce})}',
        'openid.realm': base,
        'openid.identity': IDENTIFIER_SELECT,
        'openid.claimed_id': IDENTIFIER_SELECT,
    }
    return f'{STEAM_OPENID_URL}?{urlencode(params)}'


def check_assertion_fields(params: dict[str, str], base: str, state_nonce: str) -> str:
    """
        Checks the parts of Steam's reply we can check without asking Steam.
        Return: the SteamID64 from claimed_id.
        Raises: LoginError
    """
    if params.get('openid.mode') != 'id_res':
        raise LoginError('Steam sign-in was cancelled.')
    if params.get('openid.ns') != OPENID_NS or params.get('openid.op_endpoint') != STEAM_OPENID_URL:
        raise LoginError('That sign-in reply did not come from Steam.')

    return_to = urlsplit(params.get('openid.return_to', ''))
    expected = urlsplit(f'{base}{CALLBACK_PATH}')
    if (return_to.scheme, return_to.netloc, return_to.path) != (expected.scheme, expected.netloc, expected.path):
        raise LoginError('That sign-in reply was meant for a different site.')
    if return_to.query != urlencode({'state': state_nonce}):
        raise LoginError('Sign-in expired or was started in another browser. Try again.')

    claimed_id = params.get('openid.claimed_id', '')
    match = CLAIMED_ID_RE.match(claimed_id)
    if not match or params.get('openid.identity') != claimed_id:
        raise LoginError('Steam did not return a valid account.')
    # Steam must have signed the fields we rely on
    signed = set(params.get('openid.signed', '').split(','))
    if not {'return_to', 'claimed_id', 'identity', 'op_endpoint'} <= signed:
        raise LoginError('Steam did not sign the sign-in reply.')
    return match.group(1)


async def verify_with_steam(client: httpx.AsyncClient, params: dict[str, str]) -> bool:
    """ Asks Steam whether it really sent this assertion. """
    data = {k: v for k, v in params.items() if k.startswith('openid.')}
    data['openid.mode'] = 'check_authentication'
    response = await client.post(STEAM_OPENID_URL, data=data)
    if response.status_code != 200:
        return False
    lines = dict(line.split(':', 1) for line in response.text.splitlines() if ':' in line)
    return lines.get('is_valid', '').strip() == 'true'


async def verify_login(client: httpx.AsyncClient, params: dict[str, str], base: str, state_nonce: str) -> str:
    """
        Return: the verified SteamID64.
        Raises: LoginError
    """
    steam_id = check_assertion_fields(params, base, state_nonce)
    try:
        valid = await verify_with_steam(client, params)
    except httpx.HTTPError:
        raise LoginError('Could not reach Steam to confirm the sign-in. Try again.')
    if not valid:
        raise LoginError('Steam could not confirm the sign-in. Try again.')
    return steam_id


async def public_profile(client: httpx.AsyncClient, steam_id: str) -> tuple[str, str]:
    """
        Name and avatar from the public profile XML, which needs no API key.
        Return: (persona_name, avatar_url), empty strings if unavailable.
    """
    try:
        response = await client.get(f'https://steamcommunity.com/profiles/{steam_id}', params={'xml': 1})
        text = response.text if response.status_code == 200 else ''
    except httpx.HTTPError:
        text = ''

    def field(tag: str) -> str:
        match = re.search(rf'<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>', text, re.S)
        return match.group(1).strip() if match else ''

    avatar = field('avatarFull')
    return field('steamID'), avatar if avatar.startswith('https://') else ''
