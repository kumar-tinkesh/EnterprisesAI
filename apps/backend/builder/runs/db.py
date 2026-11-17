"""Sessions and time for code that runs outside a request (workers, executors)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

_factory: Callable[[], AsyncSession] | None = None


def session_factory() -> AsyncSession:
    """A fresh session on the shared engine (or on whatever tests set)."""
    if _factory is not None:
        return _factory()
    from src.db.session import SessionLocal

    return SessionLocal()


def set_session_factory(factory: Callable[[], AsyncSession] | None) -> None:
    global _factory
    _factory = factory


def is_transient(error: BaseException) -> bool:
    """A database hiccup – the connection dropped, timed out or none was free – rather than a bug: the run should
    carry on from its checkpoint, not fail. Only database (and pool) errors count; a step's own timeout doesn't."""
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from src.db.session import is_dead_connection

    if isinstance(error, PoolTimeout):
        return True
    if isinstance(error, DBAPIError):
        return bool(error.connection_invalidated) or is_dead_connection(error)
    # The driver's own timeout reaches us unwrapped: count it only when it came from the database driver.
    tb, frames = error.__traceback__, []
    while tb is not None:
        frames.append(tb.tb_frame.f_code.co_filename)
        tb = tb.tb_next
    return is_dead_connection(error) and any("asyncpg" in f or "sqlalchemy" in f for f in frames)


async def fresh_connections() -> None:
    """Let go of every pooled connection (without waiting to close them – a dropped one may never answer); the
    next session opens a new one. After a database hiccup the others from that moment are suspect too."""
    if _factory is not None:
        return
    from src.db.session import engine

    await engine.dispose(close=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were written as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
