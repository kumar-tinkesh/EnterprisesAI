"""Vendor resource business-logic services (MCP)."""
from vendor_resources.services.mcp_service import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    grant_resource,
    list_mcp_servers,
)

__all__ = [
    "create_mcp_server",
    "list_mcp_servers",
    "get_mcp_server",
    "delete_mcp_server",
    "grant_resource",
]