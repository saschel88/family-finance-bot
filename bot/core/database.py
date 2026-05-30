from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.core.config import get_settings


def make_engine(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> AsyncEngine:
    """Create an async engine with explicit pooling per project conventions."""
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


_settings = get_settings()

engine: AsyncEngine = make_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def dispose_engine() -> None:
    """Dispose the global engine on shutdown."""
    await engine.dispose()
