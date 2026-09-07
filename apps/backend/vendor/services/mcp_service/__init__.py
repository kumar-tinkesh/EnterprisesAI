"""MCP server CRUD, registration, connection testing, and tenant grants package."""
from __future__ import annotations

from vendor.services import mcp_auth
from vendor.services.embedding import embed_server, embed_tool
from vendor.services.mcp_client import MCPClient, connect_mcp_server
from vendor.services.mcp_detect import detect_mcp_server
from vendor.services.mcp_service.connection import (
    _cleanup_server_local_repo_cache,
    _resolve_and_build_config,
    connect_registered_server,
    disconnect_mcp_server,
    disconnect_user_credential,
    test_mcp_connection,
    verify_user_credentials,
)
from vendor.services.mcp_service.crud import (
    delete_mcp_server,
    get_mcp_server,
    is_server_visible_to_user,
    list_mcp_servers,
)
from vendor.services.mcp_service.registration import (
    _GRANTABLE_RESOURCE_TYPES,
    add_mcp_server,
    create_mcp_server,
    grant_resource,
)
from vendor.services.repo_analyzer import analyze_repo_normalized

__all__ = [
    "add_mcp_server",
    "create_mcp_server",
    "grant_resource",
    "_GRANTABLE_RESOURCE_TYPES",
    "list_mcp_servers",
    "get_mcp_server",
    "delete_mcp_server",
    "is_server_visible_to_user",
    "_resolve_and_build_config",
    "test_mcp_connection",
    "connect_registered_server",
    "verify_user_credentials",
    "disconnect_mcp_server",
    "disconnect_user_credential",
    "_cleanup_server_local_repo_cache",
    # Dependencies re-exported for test monkeypatching compatibility
    "MCPClient",
    "connect_mcp_server",
    "embed_server",
    "embed_tool",
    "mcp_auth",
    "detect_mcp_server",
    "analyze_repo_normalized",
]
