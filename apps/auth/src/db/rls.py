"""PostgreSQL Row-Level-Security (RLS) context helpers.

When running against Postgres we propagate the active tenant id into the
session-local connection via ``SET LOCAL app.current_tenant`` so RLS policies
can scope rows per tenant. Non-Postgres drivers (e.g. SQLite) no-op.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.config import get_settings

_GUC_APP = "app.current_tenant"
_SUPPORTED = {"postgresql", "postgres"}


def is_supported(url: str) -> bool:
    return url.split(":", 1)[0].lower() in _SUPPORTED


async def set_tenant_context(session: AsyncSession | AsyncConnection, tenant_id: str) -> None:
    """Set the tenant id for the current transaction (Postgres only)."""
    settings = get_settings()
    if not is_supported(settings.DATABASE_URL):
        return
    await session.execute(
        __import__("sqlalchemy").text(f"SET LOCAL \"{_GUC_APP}\" = :tid"),
        {"tid": tenant_id},
    )