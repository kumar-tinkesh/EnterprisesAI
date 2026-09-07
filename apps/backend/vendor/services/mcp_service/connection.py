"""MCP server connection testing, user credential verification, self-healing, and disconnect flows."""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event

from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.embedding import embed_tool
from vendor.services.mcp_client import MCPClient

logger = logging.getLogger("vendor.mcp_service")


async def _resolve_and_build_config(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    request_credentials: dict[str, str] | None,
    tenant_id: str | None,
    user_id: str | None = None,
) -> dict:
    """Shared by ``test_mcp_connection`` and ``verify_user_credentials``: resolve auth and build MCPClient config."""
    transport = getattr(server, "transport", None)
    if server.source_type == "github" and server.command and transport in ("streamable_http", "sse", "unknown", None):
        transport = "stdio"
        server.transport = "stdio"

    auth_config = dict(server.auth_config or {})
    if server.transport:
        auth_config["transport"] = server.transport

    try:
        auth = await mcp_auth.resolve_auth(
            db,
            server_id=str(server.id),
            server_url=server.server_url,
            auth_config=auth_config,
            credentials=request_credentials,
            tenant_id=tenant_id,
            user_id=user_id,
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
        has_dir = any(a.startswith("/") or a == "." or a.startswith("./") for a in (server.args or []))
        if not has_dir:
            server.args = list(server.args or []) + ["/tmp"]

    config = {
        "transport_type": transport,
        "auth_type": auth["auth_type"],
        "credentials": auth["credentials"],
        "auth_headers": auth["headers"],
        "timeout": 30.0,
    }

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

    return config


async def test_mcp_connection(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    request_credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Step 2: Test connection and discover tools for a registered MCP server."""
    config = await _resolve_and_build_config(
        db, server=server, request_credentials=request_credentials, tenant_id=tenant_id
    )

    from vendor.services import mcp_service
    client_cls = getattr(mcp_service, "MCPClient", MCPClient)
    client = client_cls()
    result = await client.connect(config)

    server.bound_tools = result["bound_tools"]
    server.status = "VERIFIED"
    server.auth_type = result.get("auth_type", server.auth_type)
    await db.flush()

    await db.execute(delete(MCPTool).where(MCPTool.mcp_server_id == server.id))
    embed_tool_fn = getattr(mcp_service, "embed_tool", embed_tool)
    for tool_data in result["tools"]:
        tool = MCPTool(
            mcp_server_id=server.id,
            name=tool_data["name"],
            description=tool_data.get("description") or "",
            input_schema=tool_data.get("input_schema"),
        )
        await embed_tool_fn(tool)
        db.add(tool)
    await db.flush()

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


async def connect_registered_server(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    request_credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Connect endpoint helper: Natively resolve auth for a registered MCP server and test connection."""
    from vendor.services import mcp_service
    test_fn = getattr(mcp_service, "test_mcp_connection", test_mcp_connection)
    return await test_fn(
        db,
        server=server,
        request_credentials=request_credentials,
        tenant_id=tenant_id,
    )


async def verify_user_credentials(
    db: AsyncSession,
    *,
    server: VendorMCPServer,
    user_id: str,
    tenant_id: str | None,
    request_credentials: dict[str, str],
) -> dict:
    """End-user self-service connect: prove *this user's own* credentials work."""
    config = await _resolve_and_build_config(
        db,
        server=server,
        request_credentials=request_credentials,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    from vendor.services import mcp_service
    client_cls = getattr(mcp_service, "MCPClient", MCPClient)
    client = client_cls()
    result = await client.connect(config)

    await mcp_auth.store_server_credentials(
        db,
        server_id=str(server.id),
        credentials=request_credentials,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    await log_audit_event(
        db,
        action="mcp_server.user_connect",
        user_id=user_id,
        resource=f"mcp_server:{server.id}",
        detail=f"tools_discovered={len(result.get('tools', []))}",
    )

    return {
        "transport": result["transport"],
        "tool_names": [t["name"] for t in result.get("tools", [])],
        "auth_type": result.get("auth_type", server.auth_type),
    }


def _cleanup_server_local_repo_cache(server: VendorMCPServer) -> None:
    """Clean up local repo clone cache (/tmp/mcp_repos/<owner_repo>) when disconnecting or deleting an MCP server."""
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
    """Disconnect an MCP server: delete stored credentials, clear token cache, reset status to UNCONNECTED."""
    await mcp_auth.delete_server_credentials(db, server_id=str(server.id))
    mcp_auth.clear_token_cache(str(server.id))

    from vendor.services import mcp_service
    cleanup_fn = getattr(mcp_service, "_cleanup_server_local_repo_cache", _cleanup_server_local_repo_cache)
    cleanup_fn(server)

    server.status = "UNCONNECTED"
    await db.flush()
    await db.refresh(server)
    return server


async def disconnect_user_credential(db: AsyncSession, *, server_id: str, user_id: str) -> None:
    """End-user self-service disconnect: remove only *this user's own* isolated credential row and its cached token."""
    await mcp_auth.delete_user_credential(db, server_id=server_id, user_id=user_id)
    mcp_auth.clear_token_cache(server_id, user_id=user_id)
    await db.flush()
