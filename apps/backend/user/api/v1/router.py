"""FastAPI REST endpoints for the User domain (read-only MCP catalog/search).

All routes are gated by ``get_current_user`` (any authenticated user, not
just ``vendor_admin``) and reuse the Auth service's auth dependencies via
absolute imports (``src.api.deps``, ``src.db.session``). The router is
mounted by ``apps.backend.main`` (and ``apps.auth.src.main``) under
``/api/v1/vendor/resources``, alongside ``vendor.api.v1.router`` under the
same prefix (see those modules for why — point 2 of the vendor/user split
is deliberately left untouched for now), so these paths are unchanged from
before the split.

Routes:
    GET /catalog                any user  Access-filtered authorised catalog
    GET /catalog/tools          any user  Two-stage semantic tool search (query -> servers -> tools)
    GET /catalog/plan-tool-call any user  Select one tool + fill its arguments via LLM (no invocation)

Server registration/lifecycle/admin routes live in ``vendor.api.v1.router``
instead.
"""
from __future__ import annotations

from fastapi import APIRouter

from user.api.v1.catalog import get_catalog, router as catalog_router
from user.api.v1.planner import plan_tool_call_endpoint, router as planner_router
from user.api.v1.tools import router as tools_router, search_catalog_tools

router = APIRouter()

# Mount category sub-routers into the primary user router
router.include_router(catalog_router)
router.include_router(tools_router)
router.include_router(planner_router)

__all__ = [
    "router",
    "get_catalog",
    "search_catalog_tools",
    "plan_tool_call_endpoint",
]
