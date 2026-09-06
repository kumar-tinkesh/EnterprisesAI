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

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from user.api.v1.schemas import (
    CatalogEntry,
    CatalogResponse,
    PlannedToolCall,
    ToolCallPlanResponse,
    ToolSearchResponse,
    ToolSearchResult,
)
from user.services.catalog_engine import (
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
    get_relevant_tools_semantic,
)
from user.services.tool_call_planner import plan_tool_call

logger = logging.getLogger("user.router")

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
async def get_catalog(
    q: str | None = None,
    top_k: int = 5,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Access-filtered catalog. With ``q``, returns semantic-ranked top-K servers."""
    if top_k < 1:
        top_k = 1
    if top_k > 50:
        top_k = 50

    if q and q.strip():
        servers = await get_authorized_vendor_catalog_semantic(
            db, user=user, query=q.strip(), top_k=top_k
        )
    else:
        servers = await get_authorized_vendor_catalog(db, user=user)
    entries = [CatalogEntry.model_validate(s) for s in servers]
    return CatalogResponse(servers=entries, count=len(entries))


@router.get("/catalog/tools", response_model=ToolSearchResponse)
async def search_catalog_tools(
    q: str,
    top_k_servers: int = 5,
    top_k_tools: int = 8,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Two-stage semantic tool search: query -> top MCP servers -> top tools
    within them. Returns each tool's ``input_schema`` (parameters) so an LLM
    can be asked to fill them in — this endpoint does NOT call any tool.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="q is required"
        )
    top_k_servers = min(max(top_k_servers, 1), 20)
    top_k_tools = min(max(top_k_tools, 1), 50)

    matches = await get_relevant_tools_semantic(
        db,
        user=user,
        query=q.strip(),
        top_k_servers=top_k_servers,
        top_k_tools=top_k_tools,
    )
    results = [
        ToolSearchResult(
            tool_id=tool.id,
            tool_name=tool.name,
            tool_description=tool.description,
            input_schema=tool.input_schema,
            server_id=server.id,
            server_name=server.name,
            score=score,
        )
        for server, tool, score in matches
    ]
    return ToolSearchResponse(results=results, count=len(results))


@router.get("/catalog/plan-tool-call", response_model=ToolCallPlanResponse)
async def plan_tool_call_endpoint(
    q: str,
    top_k_servers: int = 5,
    top_k_tools: int = 3,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Select ONE MCP tool for the query and fill its arguments via the chat
    LLM's native function-calling, using the same access-filtered semantic
    candidates as ``GET /catalog/tools``. Does NOT call the tool — the
    response is the proposed tool + filled arguments only.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="q is required"
        )
    top_k_servers = min(max(top_k_servers, 1), 20)
    top_k_tools = min(max(top_k_tools, 1), 10)

    result = await plan_tool_call(
        db,
        user=user,
        query=q.strip(),
        top_k_servers=top_k_servers,
        top_k_tools=top_k_tools,
    )
    plan = (
        PlannedToolCall(
            tool_id=result.plan.tool_id,
            tool_name=result.plan.tool_name,
            server_id=result.plan.server_id,
            server_name=result.plan.server_name,
            arguments=result.plan.arguments,
            input_schema=result.plan.input_schema,
            model=result.plan.model,
        )
        if result.plan
        else None
    )
    return ToolCallPlanResponse(
        plan=plan,
        candidates_considered=result.candidates_considered,
        message=result.message,
    )
