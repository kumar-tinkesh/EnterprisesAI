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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were written as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
