"""
    Registers DealScout's slash commands with Discord. Run it once, and again after changing a command.

    Needs these in server/.env (or the environment). They stay on your computer; Vercel doesn't need them:
        DISCORD_APP_ID      Developer Portal > your app > General Information > Application ID
        DISCORD_BOT_TOKEN   Developer Portal > your app > Bot > Reset Token
        DISCORD_GUILD_ID    optional: a server ID, for testing. Server commands update instantly;
                            global commands (no guild ID) can take up to an hour to appear.

    Run from the server folder:
        .venv/Scripts/python scripts/register_commands.py
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

STRING, NUMBER = 3, 10
SORT_CHOICES = [
    {'name': 'List order', 'value': 'found'},
    {'name': 'Lowest price', 'value': 'price'},
    {'name': 'Biggest discount', 'value': 'discount'},
    {'name': 'Name A-Z', 'value': 'name'},
]
MAX_PRICE = {'type': NUMBER, 'name': 'max_price', 'description': 'Highest price to show (default $10)',
             'min_value': 0.5, 'max_value': 1000}
SORT = {'type': STRING, 'name': 'sort', 'description': 'How to order the deals', 'choices': SORT_CHOICES}

COMMANDS = [
    {'name': 'link', 'description': 'Connect your Discord account to DealScout by signing in with Steam'},
    {'name': 'unlink', 'description': 'Disconnect your Discord account from DealScout'},
    {'name': 'wishlist', 'description': 'Find cheap prices for games on a Steam wishlist', 'options': [
        {'type': STRING, 'name': 'steam', 'description': 'Profile link, custom name or SteamID64 (default: yours)'},
        MAX_PRICE, SORT,
    ]},
    {'name': 'library', 'description': 'Find cheap prices for games in your Steam library', 'options': [MAX_PRICE, SORT]},
]


def main():
    app_id = os.getenv('DISCORD_APP_ID')
    token = os.getenv('DISCORD_BOT_TOKEN')
    guild_id = os.getenv('DISCORD_GUILD_ID')
    if not app_id or not token:
        sys.exit('Set DISCORD_APP_ID and DISCORD_BOT_TOKEN in server/.env first.')

    path = f'/applications/{app_id}/guilds/{guild_id}/commands' if guild_id else f'/applications/{app_id}/commands'
    # PUT replaces the whole command list, so removed commands disappear too
    response = httpx.put(f'https://discord.com/api/v10{path}', json=COMMANDS,
                         headers={'Authorization': f'Bot {token}'}, timeout=15)
    if response.status_code >= 400:
        sys.exit(f'Discord said HTTP {response.status_code}: {response.text[:500]}')
    names = ', '.join('/' + c['name'] for c in response.json())
    print(f'Registered {names} ' + (f'in server {guild_id}.' if guild_id else 'globally (may take up to an hour).'))


if __name__ == '__main__':
    main()
