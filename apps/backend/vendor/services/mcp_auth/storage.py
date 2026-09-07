"""Database credential persistence and in-memory token cache for mcp_auth."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vendor.models import VendorMCPCredential
from vendor.services.mcp_auth.crypto import decrypt_credentials, encrypt_credentials

# Refresh cached tokens this many seconds before their stated expiry.
_TOKEN_EXPIRY_MARGIN = 60.0

# In-memory token cache: (server_id_or_url, tenant_id, user_id) -> token entry.
_token_cache: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}


async def store_server_credentials(
    db: AsyncSession,
    *,
    server_id: str,
    credentials: dict[str, str],
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Encrypt and upsert the credential set for a server.

    ``user_id`` given -> upserts that user's own isolated row (keyed on
    ``server_id`` + ``user_id`` alone). Otherwise, upserts the shared
    vendor-level/tenant-fallback row.
    """
    encrypted = encrypt_credentials(credentials)
    conditions = [VendorMCPCredential.server_id == server_id]
    if user_id is not None:
        conditions.append(VendorMCPCredential.user_id == user_id)
    else:
        conditions.append(VendorMCPCredential.user_id.is_(None))
        conditions.append(VendorMCPCredential.tenant_id == tenant_id)
    row = (await db.execute(select(VendorMCPCredential).where(*conditions))).scalars().first()
    if row is not None:
        row.encrypted_credentials = encrypted
        if user_id is not None:
            row.tenant_id = tenant_id
    else:
        db.add(
            VendorMCPCredential(
                server_id=server_id,
                tenant_id=tenant_id,
                user_id=user_id,
                encrypted_credentials=encrypted,
            )
        )
    await db.flush()


async def load_server_credentials(
    db: AsyncSession,
    *,
    server_id: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    allow_shared_fallback: bool = False,
) -> dict[str, str]:
    """Decrypt and return stored credentials.

    ``user_id`` given -> looks up that user's own isolated row first. By
    default (``allow_shared_fallback=False``) a user with no row of their
    own gets nothing back. Pass ``allow_shared_fallback=True`` to opt into
    the old tenant/vendor-level lookup when no per-user row exists.
    """
    if user_id is not None:
        row = (
            await db.execute(
                select(VendorMCPCredential).where(
                    VendorMCPCredential.server_id == server_id,
                    VendorMCPCredential.user_id == user_id,
                )
            )
        ).scalars().first()
        if row is not None:
            return decrypt_credentials(row.encrypted_credentials)
        if not allow_shared_fallback:
            return {}

    row = (
        await db.execute(
            select(VendorMCPCredential).where(
                VendorMCPCredential.server_id == server_id,
                VendorMCPCredential.tenant_id == tenant_id,
                VendorMCPCredential.user_id.is_(None),
            )
        )
    ).scalars().first()
    if row is None and tenant_id is not None:
        row = (
            await db.execute(
                select(VendorMCPCredential).where(
                    VendorMCPCredential.server_id == server_id,
                    VendorMCPCredential.tenant_id.is_(None),
                    VendorMCPCredential.user_id.is_(None),
                )
            )
        ).scalars().first()
    return decrypt_credentials(row.encrypted_credentials) if row else {}


async def has_user_credential(db: AsyncSession, *, server_id: str, user_id: str) -> bool:
    """Whether this specific user has connected their own credential for a server."""
    row = (
        await db.execute(
            select(VendorMCPCredential.id).where(
                VendorMCPCredential.server_id == server_id,
                VendorMCPCredential.user_id == user_id,
            )
        )
    ).scalars().first()
    return row is not None


async def delete_server_credentials(db: AsyncSession, *, server_id: str) -> None:
    """Delete every stored credential row for a server."""
    await db.execute(
        delete(VendorMCPCredential).where(VendorMCPCredential.server_id == server_id)
    )


async def delete_user_credential(db: AsyncSession, *, server_id: str, user_id: str) -> None:
    """Delete only the calling user's own isolated credential row."""
    await db.execute(
        delete(VendorMCPCredential).where(
            VendorMCPCredential.server_id == server_id,
            VendorMCPCredential.user_id == user_id,
        )
    )


# ── token cache ──


def _cache_key(
    server_id: str | None, server_url: str, tenant_id: str | None, user_id: str | None = None
):
    return (server_id or server_url, tenant_id, user_id)


def _cache_get(key) -> str | None:
    entry = _token_cache.get(key)
    if entry and entry["expires_at"] > time.time() + _TOKEN_EXPIRY_MARGIN:
        return entry["access_token"]
    return None


def _cache_put(key, token_response: dict[str, Any]) -> str:
    expires_in = int(token_response.get("expires_in") or 3600)
    _token_cache[key] = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "expires_at": time.time() + expires_in,
    }
    return token_response["access_token"]


def clear_token_cache(server_id: str | None = None, *, user_id: str | None = None) -> None:
    """Drop cached tokens: all, only one server's, or only one user's cached token."""
    if server_id is None:
        _token_cache.clear()
    elif user_id is not None:
        for key in [k for k in _token_cache if k[0] == server_id and k[2] == user_id]:
            _token_cache.pop(key, None)
    else:
        for key in [k for k in _token_cache if k[0] == server_id]:
            _token_cache.pop(key, None)
