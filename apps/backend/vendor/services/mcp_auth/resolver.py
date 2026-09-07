"""Main credential resolution orchestrator for mcp_auth."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from vendor.services.mcp_auth.crypto import McpAuthError
from vendor.services.mcp_auth.oauth import (
    _api_key_header,
    _basic_header,
    _bearer_header,
    _raw_header_passthrough,
    _resolve_oauth2,
)
from vendor.services.mcp_auth.storage import load_server_credentials

logger = logging.getLogger("vendor.mcp_auth")


async def resolve_auth(
    db: AsyncSession | None,
    *,
    server_id: str | None,
    server_url: str,
    auth_config: dict,
    credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    server_name: str = "",
) -> dict[str, Any]:
    """Resolve ready-to-use auth for an MCP server.

    Returns ``{"headers", "credentials", "auth_type", "token_source"}``.
    """
    stored: dict[str, str] = {}
    if db is not None and server_id:
        try:
            stored = await load_server_credentials(
                db, server_id=server_id, tenant_id=tenant_id, user_id=user_id
            )
        except McpAuthError:
            logger.warning("Stored credentials for %s are unreadable", server_id)

    # Request-supplied credentials win over stored ones.
    merged: dict[str, str] = {
        **stored,
        **{k: v for k, v in (credentials or {}).items() if v},
    }

    if "GITHUB_TOKEN" in merged and "GITHUB_PERSONAL_ACCESS_TOKEN" not in merged:
        merged["GITHUB_PERSONAL_ACCESS_TOKEN"] = merged["GITHUB_TOKEN"]
    elif "GITHUB_PERSONAL_ACCESS_TOKEN" in merged and "GITHUB_TOKEN" not in merged:
        merged["GITHUB_TOKEN"] = merged["GITHUB_PERSONAL_ACCESS_TOKEN"]

    transport = ((auth_config or {}).get("transport") or "").lower()
    auth_type = ((auth_config or {}).get("auth_type") or "none").lower()

    if auth_type in ("none", "env", "device_pairing") or transport == "stdio":
        return {
            "headers": {},
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials" if merged else None,
        }

    if auth_type == "basic":
        return {
            "headers": _basic_header(merged),
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials",
        }

    if auth_type == "api_key":
        return {
            "headers": _api_key_header(merged),
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials",
        }

    if auth_type == "bearer":
        token = (
            merged.get("access_token")
            or merged.get("token")
            or merged.get("bearer_token")
            or merged.get("jwt")
            or merged.get("api_key")
            or ""
        )
        return {
            "headers": _bearer_header(token) if token else {},
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials" if token else None,
        }

    if auth_type == "oauth2":
        return await _resolve_oauth2(
            db,
            server_id=server_id,
            server_url=server_url,
            server_name=server_name,
            auth_config=auth_config or {},
            credentials=merged,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    # unknown -> legacy raw header passthrough
    return {
        "headers": _raw_header_passthrough(merged),
        "credentials": merged,
        "auth_type": auth_type,
        "token_source": "passthrough",
    }
