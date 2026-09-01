"""Vendor Resources subsystem — capability catalog layer (MCP).

Phase 1 scope: MCP server CRUD, tenant resource grants, and an
access-filtered catalog.

All imports are absolute from the project root (no relative imports).
"""

from vendor_resources.router import router

__all__ = ["router"]