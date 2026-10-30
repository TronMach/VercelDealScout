"""
    Discord slash commands over the HTTP interactions endpoint (no always-on bot).

    Discord wants an answer within 3 seconds, but a deal scan takes longer. So /wishlist and /library
    answer "thinking..." (a deferred reply), and a separate request to /api/discord/work runs the scan
    and edits that reply. The scan is saved so the ◀ ▶ buttons can show other pages.
"""
import hashlib
import hmac
import logging
import os
import re

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from src import db, deals_service
from src.dealsgg_api import DealsGGAPI
from src.steam_api import Steam

logger = logging.getLogger(__name__)

DISCORD_API = 'https://discord.com/api/v10'

# Interaction types
PING = 1
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3
# Response types
PONG = 1
CHANNEL_MESSAGE = 4
DEFERRED_CHANNEL_MESSAGE = 5
UPDATE_MESSAGE = 7
# Message flags
EPHEMERAL = 64

PAGE_SIZE = 10
EMBED_COLOR = 0x00E676
PAGE_BUTTON_RE = re.compile(r'^pg:([0-9a-f]{16}):(\d+)$')
SORT_LABELS = {'found': 'list order', 'price': 'price', 'discount': 'discount', 'name': 'name'}


# ---- Request checks ----

def verify_signature(public_key_hex: str, signature_hex: str, timestamp: str, body: bytes) -> bool:
    """ Discord signs timestamp + body with Ed25519. """
    try:
        VerifyKey(bytes.fromhex(public_key_hex)).verify(timestamp.encode() + body, bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError):
        return False


def work_secret() -> str:
    """ Shared secret for /api/discord/work, derived from SESSION_SECRET so there's nothing extra to set. """
    return hmac.new(os.environ['SESSION_SECRET'].encode(), b'discord-work', hashlib.sha256).hexdigest()


def check_work_secret(value: str) -> bool:
    return hmac.compare_digest(value or '', work_secret())


# ---- Replies ----

def private(content: str, components: list | None = None) -> dict:
    data = {'content': content, 'flags': EPHEMERAL}
    if components:
        data['components'] = components
    return {'type': CHANNEL_MESSAGE, 'data': data}


def link_button(label: str, url: str) -> dict:
    return {'type': 1, 'components': [{'type': 2, 'style': 5, 'label': label, 'url': url}]}


def interaction_user_id(interaction: dict) -> str:
    user = (interaction.get('member') or {}).get('user') or interaction.get('user') or {}
    return str(user.get('id', ''))


def options_of(interaction: dict) -> dict:
    return {o['name']: o.get('value') for o in interaction.get('data', {}).get('options', [])}


def not_ready_message(base_url: str, linked: bool) -> dict:
    if not linked:
        return private('Your Discord account isn\'t linked to DealScout yet. Type **/link** to connect it.')
    return private('Add your GG.deals API key in DealScout Settings first, then try again.',
                   [link_button('Open DealScout', base_url)])


# ---- Rendering a page of deals ----

def money(value: float | None) -> str:
    return f'${value:.2f}' if value else '—'


def deal_line(deal: dict) -> str:
    prices = deal['prices']
    name = deal['name'].replace('[', '(').replace(']', ')')[:60]
    url = deal['url'] if deal['url'].startswith('https://') else f'https://store.steampowered.com/app/{deal["appid"]}'
    off = f' (−{round(deal["discount"] * 100)}%)' if deal['discount'] >= 0.01 else ''
    return (f'**[{name}]({url})** — **{money(deal["best_price"])}**{off}\n'
            f'Steam {money(prices["retail_price"])} · Keyshop {money(prices["keyshop_price"])}')


def page_count(result: dict) -> int:
    return max(1, -(-len(result['deals']) // PAGE_SIZE))


def render_page(result: dict, scan_id: str | None, page: int, base_url: str, owner: str) -> dict:
    """ One embed with up to 10 deals, plus ◀ ▶ buttons. Stays far under Discord's 6,000-character embed limit. """
    pages = page_count(result)
    page = min(max(page, 0), pages - 1)
    deals = result['deals'][page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    stats = result['stats']
    kind = 'Wishlist' if result['kind'] == 'wishlist' else 'Library'

    if deals:
        description = '\n'.join(deal_line(d) for d in deals)
    else:
        description = f'No games under {money(result["max_price"])} right now.'
    notes = []
    if result['games_scanned'] < result['games_total']:
        notes.append(f'Checked the first {result["games_scanned"]} of {result["games_total"]} games.')
    if result['rate_limited']:
        notes.append('GG.deals rate limited part of the scan; try again in a minute for the rest.')
    if notes:
        description += '\n\n*' + ' '.join(notes) + '*'

    embed = {
        'title': f'{kind} deals for {owner} under {money(result["max_price"])}'[:256],
        'description': description[:4000],
        'color': EMBED_COLOR,
        'footer': {'text': f'Page {page + 1}/{pages} · {stats["games_found"]} deals · '
                           f'lowest {money(stats["lowest_deal"])} · sorted by {SORT_LABELS.get(result["sort"], result["sort"])}'},
    }
    row = []
    if scan_id and pages > 1:
        row += [
            {'type': 2, 'style': 2, 'label': '◀', 'custom_id': f'pg:{scan_id}:{page - 1}', 'disabled': page == 0},
            {'type': 2, 'style': 2, 'label': '▶', 'custom_id': f'pg:{scan_id}:{page + 1}', 'disabled': page >= pages - 1},
        ]
    row.append({'type': 2, 'style': 5, 'label': 'Open DealScout', 'url': base_url})
    return {'content': '', 'embeds': [embed], 'components': [{'type': 1, 'components': row}]}


# ---- Handling interactions ----

async def handle_command(interaction: dict, base_url: str) -> tuple[dict, dict | None]:
    """
        Return: (reply for Discord, work for /api/discord/work or None)
    """
    name = interaction.get('data', {}).get('name')
    discord_id = interaction_user_id(interaction)

    if name == 'link':
        code = await db.create_link_code(discord_id)
        return private(f'Open this link and sign in with Steam to connect your Discord account. '
                       f'It works once and expires in {db.LINK_CODE_MINUTES} minutes.',
                       [link_button('Link with Steam', f'{base_url}/api/auth/steam/login?link={code}')]), None

    if name == 'unlink':
        unlinked = await db.unlink_discord(discord_id)
        return private('Your Discord account is no longer linked to DealScout.' if unlinked
                       else 'Your Discord account wasn\'t linked.'), None

    if name in ('wishlist', 'library'):
        user = await db.get_user_by_discord(discord_id)
        keys = await db.get_keys(user.steam_id) if user else {}
        if not user or not keys.get('deals_api_key'):
            return not_ready_message(base_url, bool(user)), None
        if name == 'library' and not keys.get('steam_api_key'):
            return private('/library needs your Steam API key. Add it in DealScout Settings.',
                           [link_button('Open DealScout', base_url)]), None
        work = {
            'application_id': interaction['application_id'],
            'token': interaction['token'],
            'command': name,
            'options': options_of(interaction),
            'discord_user_id': discord_id,
        }
        return {'type': DEFERRED_CHANNEL_MESSAGE}, work

    return private('Unknown command.'), None


async def handle_component(interaction: dict, base_url: str) -> dict:
    """ ◀ ▶ buttons: show another page of a saved scan. """
    match = PAGE_BUTTON_RE.match(interaction.get('data', {}).get('custom_id', ''))
    if not match:
        return private('That button no longer works.')
    result = await db.get_scan(match.group(1))
    if result is None:
        return private(f'That scan is older than {db.SCAN_KEEP_DAYS} days. Run the command again.')
    return {'type': UPDATE_MESSAGE,
            'data': render_page(result, match.group(1), int(match.group(2)), base_url, result.get('owner', ''))}


async def resolve_target(steam: Steam, query: str | None, own_id: str) -> str | None:
    if not query:
        return own_id
    return await steam.resolve_steam_id(str(query))


async def do_work(work: dict, base_url: str, client: httpx.AsyncClient):
    """ Runs the scan for a deferred /wishlist or /library and edits the "thinking..." reply. """
    edit_url = f'{DISCORD_API}/webhooks/{work["application_id"]}/{work["token"]}/messages/@original'

    async def edit(message: dict):
        response = await client.patch(edit_url, json=message)
        if response.status_code >= 400:
            logger.error(f'Discord edit failed: HTTP {response.status_code}')

    user = await db.get_user_by_discord(work['discord_user_id'])
    if user is None:
        await edit({'content': 'Your Discord account isn\'t linked. Type /link.'})
        return
    keys = await db.get_keys(user.steam_id)
    steam, dealsgg = Steam(keys['steam_api_key']), DealsGGAPI(keys['deals_api_key'])
    options = work['options']
    max_price = float(options.get('max_price') or deals_service.DEFAULT_MAX_PRICE)
    sort = options.get('sort') if options.get('sort') in deals_service.SORT_KEYS else 'found'

    try:
        target = user.steam_id
        owner = user.persona_name or user.steam_id
        if work['command'] == 'wishlist' and options.get('steam'):
            target = await resolve_target(steam, options['steam'], user.steam_id)
            if not target:
                await edit({'content': 'No Steam account matches that. Paste a profile link or a 17-digit SteamID64.'})
                return
            owner = target
        result = await deals_service.scan(work['command'], target, steam, dealsgg, max_price, sort)
    except deals_service.RateLimited:
        await edit({'content': 'GG.deals is rate limiting requests. Try again in a minute.'})
        return
    except ValueError:
        await edit({'content': f'No {work["command"]} found. It may be empty or private.'})
        return
    except httpx.HTTPError as error:
        logger.error(f'Discord scan failed: {type(error).__name__}')
        await edit({'content': 'Steam or GG.deals did not answer. Try again.'})
        return

    result['owner'] = owner
    scan_id = await db.save_scan(work['discord_user_id'], result) if page_count(result) > 1 else None
    await edit(render_page(result, scan_id, 0, base_url, owner))
