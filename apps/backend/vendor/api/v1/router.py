"""FastAPI REST endpoints for the Vendor domain (MCP server lifecycle)."""
from __future__ import annotations

from fastapi import APIRouter

from vendor.api.v1.connection import (
    connect_mcp_server_endpoint,
    disconnect_mcp_server_endpoint,
    embed_mcp_server,
    router as connection_router,
    test_mcp_connection_endpoint,
)
from vendor.api.v1.detection import (
    analyze_mcp_repo_endpoint,
    detect_mcp_server_endpoint,
    router as detection_router,
)
from vendor.api.v1.grants import (
    post_grant_resource,
    router as grants_router,
)
from vendor.api.v1.oauth import (
    _oauth_result_html,
    mcp_oauth_callback,
    router as oauth_router,
    set_mcp_oauth_config,
    start_mcp_oauth_authorize,
)
from vendor.api.v1.servers import (
    delete_mcp_server_endpoint,
    get_list_mcp_servers,
    post_add_mcp_server,
    post_create_mcp_server_legacy,
    router as servers_router,
)
from vendor.api.v1.user_connection import (
    connect_mcp_server_as_user_endpoint,
    disconnect_mcp_server_as_user_endpoint,
    router as user_connection_router,
)

router = APIRouter()

# Mount all category sub-routers into the primary vendor router
router.include_router(servers_router)
router.include_router(connection_router)
router.include_router(user_connection_router)
router.include_router(detection_router)
router.include_router(oauth_router)
router.include_router(grants_router)

__all__ = [
    "router",
    "post_add_mcp_server",
    "post_create_mcp_server_legacy",
    "get_list_mcp_servers",
    "delete_mcp_server_endpoint",
    "embed_mcp_server",
    "test_mcp_connection_endpoint",
    "connect_mcp_server_endpoint",
    "disconnect_mcp_server_endpoint",
    "connect_mcp_server_as_user_endpoint",
    "disconnect_mcp_server_as_user_endpoint",
    "detect_mcp_server_endpoint",
    "analyze_mcp_repo_endpoint",
    "set_mcp_oauth_config",
    "start_mcp_oauth_authorize",
    "mcp_oauth_callback",
    "_oauth_result_html",
    "post_grant_resource",
]
