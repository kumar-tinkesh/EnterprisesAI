"""MCP server registration and tenant resource grant business logic."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event
from src.models import Tenant

from vendor.api.v1.schemas import (
    AddMCPServerRequest,
    ConnectMCPServerRequest,
    GrantTenantResourceRequest,
)
from vendor.models import TenantResourceGrant, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.embedding import embed_server
from vendor.services.mcp_client import connect_mcp_server
from vendor.services.mcp_detect import detect_mcp_server
from vendor.services.repo_analyzer import analyze_repo_normalized

logger = logging.getLogger("vendor.mcp_service")

_GRANTABLE_RESOURCE_TYPES = {"mcp"}


async def add_mcp_server(
    db: AsyncSession, *, data: AddMCPServerRequest, actor_id: str
) -> VendorMCPServer:
    """Step 1: Register an MCP server from a Remote URL or GitHub repo URL."""
    logger.info(
        "mcp_source_debug",
        source_url=data.source_url,
        source_url_type=type(data.source_url).__name__,
    )
    if not data.source_url or not isinstance(data.source_url, str):
        raise ValueError(
            f"source_url must be a non-empty string, got {type(data.source_url).__name__}"
        )

    from vendor.services import mcp_service
    analyze_fn = getattr(mcp_service, "analyze_repo_normalized", analyze_repo_normalized)
    normalized = await analyze_fn(data.source_url)

    # Override with explicit fields if provided
    if data.source_type:
        normalized.source_type = data.source_type
    if data.source_subpath:
        normalized.source_subpath = data.source_subpath
        normalized.working_directory = data.source_subpath
    if data.source_branch:
        normalized.source_branch = data.source_branch

    # 2. Build auth_config from detection (for Step 2 connection)
    auth_config = {
        "auth_type": normalized.auth_type,
        "transport": normalized.transport_type,
        "credential_fields": [f.to_dict() for f in normalized.auth_fields],
        "confidence": str(normalized.transport_confidence),
        "hints": normalized.hints,
        "oauth": {},
    }

    # 3. Determine endpoint for remote transports
    endpoint = normalized.endpoint
    if normalized.source_type == "remote" and not endpoint:
        endpoint = data.source_url

    # 4. Build startup command for stdio transports
    command = normalized.command
    args = normalized.args
    working_directory = normalized.working_directory

    # 5. Create server with UNCONNECTED status — NO connection attempt here
    server = VendorMCPServer(
        name=data.name,
        description=data.description,
        status="UNCONNECTED",
        is_global=data.is_global,
        source_type=normalized.source_type,
        source_repo=normalized.source_repo,
        source_branch=normalized.source_branch,
        source_subpath=normalized.source_subpath,
        source_repo_url=data.source_url if normalized.source_type == "github" else None,
        server_url=endpoint or data.source_url,
        transport=normalized.transport_type,
        transport_confidence=normalized.transport_confidence,
        transport_evidence=[e.to_dict() for e in normalized.transport_evidence],
        runtime_type=normalized.runtime_type,
        command=command,
        args=args,
        working_directory=working_directory,
        endpoint=endpoint,
        auth_type=normalized.auth_type,
        auth_schema={
            "fields": [f.to_dict() for f in normalized.auth_fields]
        },
        auth_config=auth_config,
        env_vars={f.name: "" for f in normalized.auth_fields},
        bound_tools=[],
    )

    embed_fn = getattr(mcp_service, "embed_server", embed_server)
    await embed_fn(server)
    db.add(server)
    await db.flush()

    await log_audit_event(
        db,
        action="mcp_server.add",
        user_id=actor_id,
        resource=f"mcp_server:{server.id}",
        detail=f"name={server.name} source_type={normalized.source_type} transport={normalized.transport_type}",
    )
    return server


async def create_mcp_server(
    db: AsyncSession, *, data: ConnectMCPServerRequest, actor_id: str
) -> VendorMCPServer:
    """Legacy: Insert a new MCP server with auto-detected transport and optional connection."""
    from vendor.services import mcp_service
    detect_fn = getattr(mcp_service, "detect_mcp_server", detect_mcp_server)
    connect_fn = getattr(mcp_service, "connect_mcp_server", connect_mcp_server)

    detection = await detect_fn(data.server_url)
    auth_config = {
        "auth_type": detection["auth_type"],
        "transport": detection["transport"],
        "credential_fields": detection["credential_fields"],
        "confidence": detection["confidence"],
        "hints": detection["hints"],
        "oauth": detection.get("oauth") or {},
    }

    result: dict = {"transport": detection["transport"], "bound_tools": []}
    should_connect = bool(data.credentials) or detection["auth_type"] in ("none", "", "unknown")
    if should_connect:
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
            result = await connect_fn(
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
            if data.credentials:
                auth_config["auth_type"] = result.get("auth_type", detection["auth_type"])
        except Exception as exc:
            logger.warning("Failed to connect MCP server %s: %s", data.server_url, exc)

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
        status="VERIFIED" if result["bound_tools"] else "UNCONNECTED",
    )
    db.add(server)
    await db.flush()
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


async def grant_resource(
    db: AsyncSession, *, data: GrantTenantResourceRequest, actor_id: str
) -> tuple[TenantResourceGrant, bool]:
    """Grant a resource to a tenant."""
    if data.resource_type not in _GRANTABLE_RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource_type: {data.resource_type}")

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == data.tenant_id))
    ).scalars().first()
    if tenant is None:
        raise LookupError(f"Tenant not found: {data.tenant_id}")

    if data.resource_type == "mcp":
        from vendor.services import mcp_service
        get_server_fn = getattr(mcp_service, "get_mcp_server", None)
        resource = await get_server_fn(db, data.resource_id) if get_server_fn else None
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
