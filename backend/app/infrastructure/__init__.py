"""Infrastructure — database engine, models, repositories."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
    future=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async DB session."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create tables on startup."""
    from app.infrastructure import models  # noqa: F401 — ensure models registered

    from sqlalchemy.orm import DeclarativeBase

    # Our Base is defined in models.py
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
