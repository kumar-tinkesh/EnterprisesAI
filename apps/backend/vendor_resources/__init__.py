"""Vendor Resources subsystem — capability catalog layer.

Phase 1 scope: Vendor Tools CRUD, tenant resource grants, and an
access-filtered catalog. MCP servers, RAG data sources, semantic matching and
the AI Compiler are deferred to later phases.

All imports are absolute from the project root (no relative imports).
"""

from vendor_resources.router import router

__all__ = ["router"]