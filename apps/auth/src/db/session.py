"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.config import get_settings
from src.models import *  # noqa: F401,F403  (register models on the metadata)

settings = get_settings()

engine_kwargs: dict = {"echo": settings.DB_ECHO}
# SQLite in-memory requires NullPool to avoid cross-connection empty DBs.
if "sqlite" in settings.DATABASE_URL and ":memory:" in settings.DATABASE_URL:
    engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
SessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a scoped async session."""
    async with SessionLocal() as session:
        yield session


async def create_db_tables() -> None:
    """Create all tables from the ORM metadata (dev/seed convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)