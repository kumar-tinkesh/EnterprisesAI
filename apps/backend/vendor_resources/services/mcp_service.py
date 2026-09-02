"""MCP server CRUD + tenant grant business logic.

Each mutating service records a security audit event (via the reused
``src.core.audit.log_audit_event``) and flushes; the **caller** commits so
the entity and its audit row persist atomically.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event
from src.models import Tenant

from vendor_resources.models import TenantResourceGrant, VendorMCPServer
from vendor_resources.schemas import ConnectMCPServerRequest, GrantTenantResourceRequest, AnalyzeRepoResponse
from vendor_resources.services import mcp_auth
from vendor_resources.services.mcp_client import connect_mcp_server
from vendor_resources.services.mcp_detect import detect_mcp_server

logger = logging.getLogger("vendor_resources.mcp_service")

_GRANTABLE_RESOURCE_TYPES = {"mcp"}


async def create_mcp_server(
    db: AsyncSession, *, data: ConnectMCPServerRequest, actor_id: str
) -> VendorMCPServer:
    """Insert a new MCP server with auto-detected transport, bound tools and
    natively detected credential requirements (``auth_config``).

    Flow mirrors MRKTPLCE: probe the URL to learn which credential type it
    wants, then (optionally, if credentials were supplied) perform the real
    MCP handshake to catalogue tools.
    """
    # 1. Native detection: what does this URL want? (standards-driven —
    #    WWW-Authenticate challenges + RFC 8414/9728 OAuth metadata.)
    detection = await detect_mcp_server(data.server_url)
    auth_config = {
        "auth_type": detection["auth_type"],
        "transport": detection["transport"],
        "credential_fields": detection["credential_fields"],
        "confidence": detection["confidence"],
        "hints": detection["hints"],
        # Discovered OAuth endpoints — consumed natively at connect time so
        # tokens can be acquired/refreshed without re-probing.
        "oauth": detection.get("oauth") or {},
    }

    # 2. Resolve auth natively (OAuth2 token acquisition / api_key / basic /
    #    bearer header building) and connect for tool discovery — the detected
    #    endpoint may differ from the input URL (e.g. base URL + /sse).
    result: dict = {"transport": detection["transport"], "bound_tools": []}
    try:
        auth = await mcp_auth.resolve_auth(
            None,
            server_id=None,
            server_url=data.server_url,
            auth_config=auth_config,
            credentials=data.credentials,
            server_name=data.name,
        )
    except mcp_auth.McpAuthError as exc:
        logger.warning(
            "Could not natively resolve credentials for %s: %s", data.server_url, exc
        )
        auth = {"headers": {}, "credentials": data.credentials or {}}
    try:
        result = await connect_mcp_server(
            detection["endpoint"],
            credentials=auth["credentials"],
            transport=(
                "sse"
                if detection["transport"] == "sse"
                else None
            ),
            auth_type=detection["auth_type"],
            auth_headers=auth["headers"],
            source_repo_url=data.source_repo_url,
            env_vars=data.env_vars if isinstance(data.env_vars, dict) else None,
        )
        # Successful handshake (possibly with credentials) proves the
        # requirement: remember the auth type actually used.
        if data.credentials:
            auth_config["auth_type"] = result.get("auth_type", detection["auth_type"])
    except Exception as exc:
        logger.warning("Failed to auto-connect MCP server %s: %s", data.server_url, exc)

    server = VendorMCPServer(
        name=data.name,
        description=data.description,
        transport=result["transport"],
        server_url=data.server_url,
        source_repo_url=data.source_repo_url,
        env_vars=data.env_vars,
        bound_tools=result["bound_tools"],
        auth_config=auth_config,
        is_global=data.is_global,
    )
    db.add(server)
    await db.flush()
    # Persist supplied credentials encrypted so future connections resolve
    # auth natively (OAuth2 refresh/client_credentials, api_key, basic…).
    if data.credentials:
        await mcp_auth.store_server_credentials(
            db, server_id=str(server.id), credentials=data.credentials
        )
    await log_audit_event(
        db,
        action="mcp_server.create",
        user_id=actor_id,
        resource=f"mcp_server:{server.id}",
        detail=f"name={server.name}",
    )
    return server


async def list_mcp_servers(db: AsyncSession) -> list[VendorMCPServer]:
    """Return all registered MCP servers (admin view)."""
    result = await db.execute(select(VendorMCPServer).order_by(VendorMCPServer.created_at.desc()))
    return list(result.scalars().all())


async def get_mcp_server(db: AsyncSession, server_id: str) -> Optional[VendorMCPServer]:
    """Return a single MCP server by id, or None."""
    result = await db.execute(select(VendorMCPServer).where(VendorMCPServer.id == server_id))
    return result.scalars().first()


async def delete_mcp_server(
    db: AsyncSession, *, server_id: str, actor_id: str
) -> bool:
    """Delete an MCP server and cascade-delete its tenant grants."""
    server = await get_mcp_server(db, server_id)
    if server is None:
        return False

    await db.execute(
        delete(TenantResourceGrant).where(
            TenantResourceGrant.resource_id == server_id,
            TenantResourceGrant.resource_type == "mcp",
        )
    )
    # Cascade-delete any stored (encrypted) credentials for this server.
    await mcp_auth.delete_server_credentials(db, server_id=server_id)
    mcp_auth.clear_token_cache(server_id)
    await db.delete(server)
    await db.flush()
    await log_audit_event(
        db,
        action="mcp_server.delete",
        user_id=actor_id,
        resource=f"mcp_server:{server_id}",
    )
    return True


async def grant_resource(
    db: AsyncSession, *, data: GrantTenantResourceRequest, actor_id: str
) -> tuple[TenantResourceGrant, bool]:
    """Grant a resource to a tenant.

    Validates that the tenant and resource exist. Idempotent: a duplicate
    grant returns the existing row (created=False) instead of erroring.
    """
    if data.resource_type not in _GRANTABLE_RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource_type: {data.resource_type}")

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == data.tenant_id))
    ).scalars().first()
    if tenant is None:
        raise LookupError(f"Tenant not found: {data.tenant_id}")

    if data.resource_type == "mcp":
        resource = await get_mcp_server(db, data.resource_id)
        if resource is None:
            raise LookupError(f"MCP server not found: {data.resource_id}")

    existing = (
        await db.execute(
            select(TenantResourceGrant).where(
                TenantResourceGrant.tenant_id == data.tenant_id,
                TenantResourceGrant.resource_type == data.resource_type,
                TenantResourceGrant.resource_id == data.resource_id,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing, False

    grant = TenantResourceGrant(
        tenant_id=data.tenant_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
    )
    db.add(grant)
    try:
        await db.flush()
    except Exception:
        await db.rollback()
        existing = (
            await db.execute(
                select(TenantResourceGrant).where(
                    TenantResourceGrant.tenant_id == data.tenant_id,
                    TenantResourceGrant.resource_type == data.resource_type,
                    TenantResourceGrant.resource_id == data.resource_id,
                )
            )
        ).scalars().first()
        if existing is None:
            raise
        return existing, False

    await log_audit_event(
        db,
        action="tenant_resource.grant",
        user_id=actor_id,
        tenant_id=data.tenant_id,
        resource=f"{data.resource_type}:{data.resource_id}",
    )
    return grant, True


async def connect_registered_server(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    request_credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Natively resolve auth for a registered MCP server and run the handshake.

    Credential resolution order (via ``mcp_auth.resolve_auth``): stored
    encrypted credentials, overridden by ``request_credentials`` — then, per
    the server's detected auth type, OAuth2 token acquisition (cache →
    refresh_token → client_credentials → dynamic registration → passthrough),
    API-key/basic/bearer header building, or nothing for open servers.

    Returns the ``connect_mcp_server`` result dict with the effective
    ``auth_type`` attached.
    """
    auth = await mcp_auth.resolve_auth(
        db,
        server_id=str(server.id),
        server_url=server.server_url,
        auth_config=server.auth_config or {},
        credentials=request_credentials,
        tenant_id=tenant_id,
        server_name=server.name,
    )
    result = await connect_mcp_server(
        server.server_url,
        credentials=auth["credentials"],
        auth_headers=auth["headers"] or None,
        source_repo_url=server.source_repo_url,
        env_vars=server.env_vars if isinstance(server.env_vars, dict) else None,
    )
    result["auth_type"] = auth["auth_type"]
    return result


__all__ = [
    "connect_registered_server",
    "create_mcp_server",
    "list_mcp_servers",
    "get_mcp_server",
    "delete_mcp_server",
    "grant_resource",
]