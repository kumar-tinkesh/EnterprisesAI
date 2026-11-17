"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
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
elif "sqlite" not in settings.DATABASE_URL:
    # Past these, a session waits for a free connection instead of opening one the server refuses.
    engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW, pool_timeout=settings.DB_POOL_TIMEOUT,
    )

_ASYNCPG = "+asyncpg" in settings.DATABASE_URL
if _ASYNCPG:
    engine_kwargs.update(
        # Checked before use, and replaced when old: a connection the network dropped is never handed out.
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        connect_args={"command_timeout": settings.DB_COMMAND_TIMEOUT, "timeout": settings.DB_CONNECT_TIMEOUT},
    )

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Messages of a driver error that mean the connection itself is gone or stuck, not that the query was wrong.
_DEAD = ("connection was closed", "connection is closed", "another operation is in progress", "timeout",
         "timed out", "connection reset", "broken pipe", "ssl", "connectiondoesnotexist")


def is_dead_connection(error: BaseException) -> bool:
    """Is this error a connection that died or stopped answering (as opposed to a bad query)?"""
    import asyncio

    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
            return True
        if any(word in f"{type(error).__name__}: {error}".lower() for word in _DEAD):
            return True
        error = error.__cause__ or error.__context__
    return False


if _ASYNCPG:
    @event.listens_for(engine.sync_engine, "handle_error")
    def _drop_dead_connections(context) -> None:
        """A query that timed out on a connection the network dropped leaves that connection unusable, but the
        driver only calls a connection "closed" when the socket says so – so it would go back to the pool and
        hang the next step. Count it as a disconnect: the pool throws it (and its siblings) away."""
        if is_dead_connection(context.original_exception):
            context.is_disconnect = True
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