"""Veritabanı bağlantısı — async SQLAlchemy engine + session fabrikası.

Dev: SQLite (aiosqlite). Üretim: Postgres (asyncpg). Tek fark: DATABASE_URL.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..core.config import get_settings
from .orm import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """Tabloları oluşturur (MVP — migration yerine create_all). TODO(Faz 2): Alembic."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
