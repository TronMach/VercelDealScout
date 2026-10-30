"""
    Database tables and access.
    Locally: SQLite file server/dealscout.db. On Vercel: Postgres (Neon) from DATABASE_URL.
    Tables are created on first use; there are no migrations yet.
"""
import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import DateTime, ForeignKey, String, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from src import crypto

LOCAL_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'dealscout.db')
LINK_CODE_MINUTES = 10
# Discord page buttons work for this long after a scan
SCAN_KEEP_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    steam_id: Mapped[str] = mapped_column(String(17), primary_key=True)
    persona_name: Mapped[str] = mapped_column(String(64), default='')
    avatar_url: Mapped[str] = mapped_column(String(255), default='')
    discord_user_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserKeys(Base):
    __tablename__ = 'user_keys'
    steam_id: Mapped[str] = mapped_column(ForeignKey('users.steam_id', ondelete='CASCADE'), primary_key=True)
    steam_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    deals_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    discord_webhook_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscordLinkCode(Base):
    __tablename__ = 'discord_link_codes'
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscordScan(Base):
    """ A scan shown in Discord, kept so the page buttons can show other pages. """
    __tablename__ = 'discord_scans'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String(20))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def database_url() -> tuple[str, dict]:
    """
        Turns DATABASE_URL into an async SQLAlchemy URL and connect args.
        Neon gives postgres://...?sslmode=require; asyncpg wants ssl as a connect arg instead.
    """
    url = os.getenv('DATABASE_URL', '')
    if not url:
        return f'sqlite+aiosqlite:///{LOCAL_DB_PATH}', {}
    if url.startswith('sqlite'):
        return url, {}

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    ssl_mode = query.pop('sslmode', None)
    query.pop('channel_binding', None)
    connect_args = {'ssl': 'require'} if ssl_mode in ('require', 'verify-ca', 'verify-full') else {}
    return urlunsplit(('postgresql+asyncpg', parts.netloc, parts.path, urlencode(query), '')), connect_args


# One engine per event loop: asyncpg connections can't move between loops
_engines: dict[int, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]] = {}
_tables_ready: set[int] = set()


async def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _engines:
        url, connect_args = database_url()
        # Serverless functions come and go, so don't hold pooled connections open (Neon pools for us)
        engine = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)
        _engines[loop_id] = (engine, async_sessionmaker(engine, expire_on_commit=False))
    engine, maker = _engines[loop_id]
    if loop_id not in _tables_ready:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tables_ready.add(loop_id)
    return maker


async def dispose_engines():
    for engine, _ in _engines.values():
        await engine.dispose()
    _engines.clear()
    _tables_ready.clear()


# ---- Users ----

async def upsert_user(steam_id: str, persona_name: str = '', avatar_url: str = '') -> User:
    maker = await get_sessionmaker()
    async with maker() as session:
        user = await session.get(User, steam_id)
        if user is None:
            user = User(steam_id=steam_id)
            session.add(user)
        if persona_name:
            user.persona_name = persona_name[:64]
        if avatar_url:
            user.avatar_url = avatar_url[:255]
        await session.commit()
        return user


async def get_user(steam_id: str) -> User | None:
    maker = await get_sessionmaker()
    async with maker() as session:
        return await session.get(User, steam_id)


async def get_user_by_discord(discord_user_id: str) -> User | None:
    maker = await get_sessionmaker()
    async with maker() as session:
        result = await session.execute(select(User).where(User.discord_user_id == discord_user_id))
        return result.scalar_one_or_none()


# ---- Keys (plaintext only in memory; stored encrypted) ----

KEY_NAMES = ('steam_api_key', 'deals_api_key', 'discord_webhook')


async def get_keys(steam_id: str) -> dict[str, str]:
    """ Return: {'steam_api_key', 'deals_api_key', 'discord_webhook'} in plaintext, '' when not set. """
    maker = await get_sessionmaker()
    async with maker() as session:
        row = await session.get(UserKeys, steam_id)
    return {name: crypto.decrypt(getattr(row, f'{name}_enc')) if row else '' for name in KEY_NAMES}


async def set_keys(steam_id: str, **keys: str | None):
    """
        Saves the given keys encrypted. A value of None leaves that key alone; '' removes it.
        Names: steam_api_key, deals_api_key, discord_webhook.
    """
    maker = await get_sessionmaker()
    async with maker() as session:
        row = await session.get(UserKeys, steam_id)
        if row is None:
            row = UserKeys(steam_id=steam_id)
            session.add(row)
        for name, value in keys.items():
            if name not in KEY_NAMES:
                raise ValueError(f'Unknown key name: {name}')
            if value is None:
                continue
            setattr(row, f'{name}_enc', crypto.encrypt(value) if value else None)
        row.updated_at = utcnow()
        await session.commit()


# ---- Discord linking ----

async def create_link_code(discord_user_id: str) -> str:
    """ A single-use code, valid for 10 minutes, that links a Discord user to whoever signs in with it. """
    code = secrets.token_urlsafe(24)
    maker = await get_sessionmaker()
    async with maker() as session:
        await session.execute(delete(DiscordLinkCode).where(DiscordLinkCode.expires_at < utcnow()))
        session.add(DiscordLinkCode(code=code, discord_user_id=discord_user_id,
                                    expires_at=utcnow() + timedelta(minutes=LINK_CODE_MINUTES)))
        await session.commit()
    return code


async def redeem_link_code(code: str, steam_id: str) -> bool:
    """ Links the code's Discord user to steam_id. The code is used up either way. Return: True if linked. """
    maker = await get_sessionmaker()
    async with maker() as session:
        row = await session.get(DiscordLinkCode, code)
        if row is None:
            return False
        await session.delete(row)
        user = await session.get(User, steam_id)
        if as_utc(row.expires_at) < utcnow() or user is None:
            await session.commit()
            return False

        # A Discord account links to one Steam account at a time
        result = await session.execute(select(User).where(User.discord_user_id == row.discord_user_id))
        previous = result.scalar_one_or_none()
        if previous is not None and previous.steam_id != steam_id:
            previous.discord_user_id = None
            await session.flush()
        user.discord_user_id = row.discord_user_id
        await session.commit()
        return True


async def unlink_discord(discord_user_id: str) -> bool:
    maker = await get_sessionmaker()
    async with maker() as session:
        result = await session.execute(select(User).where(User.discord_user_id == discord_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return False
        user.discord_user_id = None
        await session.commit()
        return True


# ---- Discord scans (for page buttons) ----

async def save_scan(discord_user_id: str, result: dict) -> str:
    scan_id = secrets.token_hex(8)
    maker = await get_sessionmaker()
    async with maker() as session:
        await session.execute(delete(DiscordScan).where(DiscordScan.created_at < utcnow() - timedelta(days=SCAN_KEEP_DAYS)))
        session.add(DiscordScan(id=scan_id, discord_user_id=discord_user_id, result_json=json.dumps(result)))
        await session.commit()
    return scan_id


async def get_scan(scan_id: str) -> dict | None:
    maker = await get_sessionmaker()
    async with maker() as session:
        row = await session.get(DiscordScan, scan_id)
    return json.loads(row.result_json) if row else None
