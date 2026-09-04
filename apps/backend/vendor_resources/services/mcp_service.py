"""MCP server CRUD + tenant grant business logic.

Each mutating service records a security audit event (via the reused
``src.core.audit.log_audit_event``) and flushes; the **caller** commits so
the entity and its audit row persist atomically.

Implements the Universal MCP Server Add & Connection Flow (two-step):
  Step 1 — Register: analyze source, detect transport/runtime/auth, save normalized config.
                  Does NOT connect if credentials missing. Returns 201, status=UNCONNECTED.
  Step 2 — Test Connection: user provides credentials via dynamic form, connect,
                  run initialize + tools/list, save tools, status=VERIFIED.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event
from src.models import Tenant

from vendor_resources.models import TenantResourceGrant, VendorMCPServer
from vendor_resources.schemas import (
    AddMCPServerRequest,
    ConnectMCPServerRequest,
    GrantTenantResourceRequest,
    AnalyzeRepoResponse,
)
from vendor_resources.services import mcp_auth
from vendor_resources.services.mcp_client import connect_mcp_server, MCPClient
from vendor_resources.services.mcp_detect import detect_mcp_server
from vendor_resources.services.repo_analyzer import analyze_repo_normalized, NormalizedMCPConfig

logger = logging.getLogger("vendor_resources.mcp_service")

_GRANTABLE_RESOURCE_TYPES = {"mcp"}


async def add_mcp_server(
    db: AsyncSession, *, data: AddMCPServerRequest, actor_id: str
) -> VendorMCPServer:
    """Step 1: Register an MCP server from a Remote URL or GitHub repo URL.

    Analyzes the source, detects transport/runtime/auth, builds normalized config,
    and saves the server with status=UNCONNECTED. Does NOT attempt connection
    if credentials are missing (per architecture Rule 7).
    """
    # 1. Analyze the source (remote URL or GitHub repo)
    logger.info(
        "mcp_source_debug",
        source_url=data.source_url,
        source_url_type=type(data.source_url).__name__,
    )
    if not data.source_url or not isinstance(data.source_url, str):
        raise ValueError(
            f"source_url must be a non-empty string, got {type(data.source_url).__name__}"
        )

    normalized = await analyze_repo_normalized(data.source_url)

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
        # Source
        source_type=normalized.source_type,
        source_repo=normalized.source_repo,
        source_branch=normalized.source_branch,
        source_subpath=normalized.source_subpath,
        source_repo_url=data.source_url if normalized.source_type == "github" else None,
        server_url=endpoint or data.source_url,
        # Transport (with evidence)
        transport=normalized.transport_type,
        transport_confidence=normalized.transport_confidence,
        transport_evidence=[e.to_dict() for e in normalized.transport_evidence],
        # Runtime
        runtime_type=normalized.runtime_type,
        # Startup (stdio)
        command=command,
        args=args,
        working_directory=working_directory,
        # Remote endpoint
        endpoint=endpoint,
        # Auth
        auth_type=normalized.auth_type,
        auth_schema={
            "fields": [f.to_dict() for f in normalized.auth_fields]
        },
        auth_config=auth_config,
        # Legacy
        env_vars={f.name: "" for f in normalized.auth_fields},
        bound_tools=[],
    )
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
    """Legacy: Insert a new MCP server with auto-detected transport and optional connection.

    Kept for backward compatibility. New code should use add_mcp_server() for Step 1
    and connect_mcp_server_endpoint() for Step 2.
    """
    # 1. Native detection: what does this URL want?
    detection = await detect_mcp_server(data.server_url)
    auth_config = {
        "auth_type": detection["auth_type"],
        "transport": detection["transport"],
        "credential_fields": detection["credential_fields"],
        "confidence": detection["confidence"],
        "hints": detection["hints"],
        "oauth": detection.get("oauth") or {},
    }

    # 2. Connect for tool discovery if credentials are supplied or server requires no auth.
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


async def test_mcp_connection(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    request_credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Step 2: Test connection and discover tools for a registered MCP server.

    Resolves auth (stored + request credentials), connects via generic MCPClient,
    runs initialize + tools/list, saves discovered tools, updates status to VERIFIED.
    """
    # Determine transport (with self-healing for GitHub repositories with local commands)
    transport = getattr(server, "transport", None)
    if server.source_type == "github" and server.command and transport in ("streamable_http", "sse", "unknown", None):
        transport = "stdio"
        server.transport = "stdio"

    auth_config = dict(server.auth_config or {})
    if server.transport:
        auth_config["transport"] = server.transport

    # Resolve auth (stored creds + request creds + OAuth flows)
    try:
        auth = await mcp_auth.resolve_auth(
            db,
            server_id=str(server.id),
            server_url=server.server_url,
            auth_config=auth_config,
            credentials=request_credentials,
            tenant_id=tenant_id,
            server_name=server.name,
        )
    except mcp_auth.McpAuthError as exc:
        logger.warning(
            "Could not natively resolve credentials for %s: %s", server.server_url, exc
        )
        auth = {"headers": {}, "credentials": request_credentials or {}}

    # Self-healing for Go commands with invalid module path or missing stdio subcommand
    if server.command == "go" or getattr(server, "runtime_type", None) == "go":
        if server.args and len(server.args) >= 2 and server.args[0] == "run" and "github.com" in server.args[1]:
            server.args = ["run", "."]
        if "stdio" not in (server.args or []):
            server.args = list(server.args or []) + ["stdio"]
    else:
        # Strip accidental 'stdio' positional args from non-Go servers (Node, Python, npx, etc.)
        if server.args and "stdio" in server.args:
            server.args = [a for a in server.args if a != "stdio"]

    # Self-healing for CLI tools with missing positional path arguments (e.g. server-filesystem)
    is_filesystem = (
        "filesystem" in (server.name or "").lower()
        or "filesystem" in (server.server_url or "").lower()
        or "filesystem" in " ".join(server.args or [])
    )
    if is_filesystem:
        # If no valid directory path (/ or .) is present in args, default to /tmp
        has_dir = any(a.startswith("/") or a == "." or a.startswith("./") for a in (server.args or []))
        if not has_dir:
            server.args = list(server.args or []) + ["/tmp"]

    # Build config for generic MCPClient
    config = {
        "transport_type": transport,
        "auth_type": auth["auth_type"],
        "credentials": auth["credentials"],
        "auth_headers": auth["headers"],
        "timeout": 30.0,
    }

    # Transport-specific config
    if transport == "stdio":
        config.update({
            "command": server.command,
            "args": server.args or [],
            "working_directory": server.working_directory,
            "source_repo_url": server.source_repo_url or server.server_url,
            "env_vars": server.env_vars,
        })
    elif transport in ("streamable_http", "sse"):
        config.update({
            "endpoint": server.endpoint or server.server_url,
        })

    # Connect via generic client
    client = MCPClient()
    result = await client.connect(config)

    # Update server with discovered tools and VERIFIED status
    server.bound_tools = result["bound_tools"]
    server.status = "VERIFIED"
    server.auth_type = result.get("auth_type", server.auth_type)
    await db.flush()

    # Persist any rotated OAuth tokens / dynamic registrations
    if request_credentials:
        await mcp_auth.store_server_credentials(
            db, server_id=str(server.id), credentials=request_credentials, tenant_id=tenant_id
        )

    await log_audit_event(
        db,
        action="mcp_server.test_connection",
        user_id=tenant_id or "system",
        resource=f"mcp_server:{server.id}",
        detail=f"tools_discovered={len(result['bound_tools'])}",
    )

    return {
        "transport": result["transport"],
        "bound_tools": result["bound_tools"],
        "tools": result["tools"],
        "server_info": result.get("server_info"),
        "protocol_version": result.get("protocol_version"),
        "auth_type": result.get("auth_type", server.auth_type),
        "status": "VERIFIED",
    }


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
    await mcp_auth.delete_server_credentials(db, server_id=server_id)
    mcp_auth.clear_token_cache(server_id)
    _cleanup_server_local_repo_cache(server)
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
    """Grant a resource to a tenant."""
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
    """Connect endpoint helper: Natively resolve auth for a registered MCP server and test connection.

    Delegates to ``test_mcp_connection()`` to ensure proper transport routing
    (stdio vs HTTP/SSE) and self-healing of server configuration.
    """
    return await test_mcp_connection(
        db,
        server=server,
        request_credentials=request_credentials,
        tenant_id=tenant_id,
    )


def _cleanup_server_local_repo_cache(server: VendorMCPServer) -> None:
    """Clean up local repo clone cache (/tmp/mcp_repos/<owner_repo>) when disconnecting or deleting an MCP server."""
    import re
    import shutil
    from pathlib import Path

    url = getattr(server, "source_repo_url", None)
    if not url or "github.com" not in url:
        return

    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", url)
    if match:
        owner, repo = match.groups()
        target = Path("/tmp/mcp_repos") / f"{owner}_{repo}"
        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass


async def disconnect_mcp_server(
    db: AsyncSession, *, server: VendorMCPServer, tenant_id: str | None = None
) -> VendorMCPServer:
    """Disconnect an MCP server: delete stored credentials, clear token cache, reset status to UNCONNECTED, and purge local repo cache."""
    await mcp_auth.delete_server_credentials(db, server_id=str(server.id))
    mcp_auth.clear_token_cache(str(server.id))
    _cleanup_server_local_repo_cache(server)
    server.status = "UNCONNECTED"
    await db.flush()
    await db.refresh(server)
    return server


__all__ = [
    "add_mcp_server",
    "test_mcp_connection",
    "create_mcp_server",
    "connect_registered_server",
    "disconnect_mcp_server",
    "list_mcp_servers",
    "get_mcp_server",
    "delete_mcp_server",
    "grant_resource",
]