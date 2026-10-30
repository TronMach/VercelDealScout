import asyncio
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from src import crypto, db


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite+aiosqlite:///{tmp_path / "test.db"}')
    monkeypatch.setenv('ENCRYPTION_KEY', Fernet.generate_key().decode())
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def run(coro_fn):
    """ Runs a test body and closes its engine on the same event loop. """
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await db.dispose_engines()
    return asyncio.run(wrapper())


def test_encryption_round_trip():
    token = crypto.encrypt('ABCDEF1234')
    assert token != 'ABCDEF1234'
    assert crypto.decrypt(token) == 'ABCDEF1234'
    assert crypto.hint('ABCDEF1234') == '••••1234'


def test_decrypt_with_another_key_gives_empty():
    token = crypto.encrypt('secret')
    crypto._fernet.cache_clear()
    import os
    os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    assert crypto.decrypt(token) == ''
    assert crypto.decrypt(None) == ''


def test_keys_are_stored_encrypted():
    async def body():
        await db.upsert_user('76561197960435530', 'Robin', '')
        await db.set_keys('76561197960435530', steam_api_key='STEAMKEY1234', deals_api_key='DEALSKEY9876')
        maker = await db.get_sessionmaker()
        async with maker() as session:
            row = await session.get(db.UserKeys, '76561197960435530')
        assert 'STEAMKEY1234' not in row.steam_api_key_enc
        keys = await db.get_keys('76561197960435530')
        assert keys == {'steam_api_key': 'STEAMKEY1234', 'deals_api_key': 'DEALSKEY9876', 'discord_webhook': ''}

        # None keeps a key, '' removes it
        await db.set_keys('76561197960435530', steam_api_key=None, deals_api_key='')
        keys = await db.get_keys('76561197960435530')
        assert keys['steam_api_key'] == 'STEAMKEY1234'
        assert keys['deals_api_key'] == ''
    run(body)


def test_link_code_is_single_use_and_moves_discord_link():
    async def body():
        await db.upsert_user('76561197960435530')
        await db.upsert_user('76561197960435531')

        code = await db.create_link_code('111')
        assert await db.redeem_link_code(code, '76561197960435530') is True
        assert await db.redeem_link_code(code, '76561197960435530') is False
        assert (await db.get_user_by_discord('111')).steam_id == '76561197960435530'

        # Linking the same Discord user to another Steam account moves the link
        code = await db.create_link_code('111')
        assert await db.redeem_link_code(code, '76561197960435531') is True
        assert (await db.get_user_by_discord('111')).steam_id == '76561197960435531'
        assert (await db.get_user('76561197960435530')).discord_user_id is None

        assert await db.unlink_discord('111') is True
        assert await db.get_user_by_discord('111') is None
    run(body)


def test_expired_link_code_is_rejected():
    async def body():
        await db.upsert_user('76561197960435530')
        code = await db.create_link_code('222')
        maker = await db.get_sessionmaker()
        async with maker() as session:
            row = await session.get(db.DiscordLinkCode, code)
            row.expires_at = db.utcnow() - timedelta(minutes=1)
            await session.commit()
        assert await db.redeem_link_code(code, '76561197960435530') is False
    run(body)


def test_neon_url_is_converted_for_asyncpg(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require')
    url, args = db.database_url()
    assert url == 'postgresql+asyncpg://u:p@ep-x.neon.tech/db'
    assert args == {'ssl': 'require'}
