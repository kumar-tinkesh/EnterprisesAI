"""FastAPI REST endpoints for the Vendor Resources subsystem.

All routes reuse the Auth service's auth/RBAC dependencies via absolute imports
(``src.api.deps``, ``src.core.roles``, ``src.db.session``) — no duplicate auth
code. The router is mounted by ``apps.backend.main`` under
``/api/v1/vendor/resources``.

Routes (Phase 1):
    POST   /tools        vendor_admin   register a vendor tool
    GET    /tools        vendor_admin   list all tools
    GET    /catalog      any user       access-filtered authorised catalog
    POST   /grants       vendor_admin   grant a resource to a tenant
    DELETE /{id}         vendor_admin   delete a tool (cascades grants)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor_resources.schemas import (
    CatalogEntry,
    CatalogResponse,
    CompileAgentRequest,
    CompiledAgentSpec,
    CreateVendorToolRequest,
    GrantResponse,
    GrantTenantResourceRequest,
    RunAgentRequest,
    RunAgentResponse,
    VendorToolResponse,
)
from vendor_resources.services.catalog_engine import (
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
)
from vendor_resources.services.compiler import compile_agent
from vendor_resources.services.executor import execute_spec
from vendor_resources.services.tool_service import (
    create_tool,
    delete_tool,
    embed_tool,
    grant_resource,
    list_tools,
)

logger = logging.getLogger("vendor_resources.router")

router = APIRouter()

_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


# ── Vendor Tool management (admin) ───────────────────────────────────────────


@router.post(
    "/tools",
    response_model=VendorToolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_create_tool(
    payload: CreateVendorToolRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    tool = await create_tool(db, data=payload, actor_id=user.id)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("/tools", response_model=list[VendorToolResponse])
async def get_list_tools(
    _user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    return await list_tools(db)


@router.post("/tools/{tool_id}/embed", status_code=status.HTTP_204_NO_CONTENT)
async def embed_vendor_tool(
    tool_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """(Re)compute a tool's semantic embedding (admin).

    Used to embed pre-existing tools (e.g. the seeded defaults) or to refresh
    after changing the embedding model.
    """
    found = await embed_tool(db, tool_id=tool_id, actor_id=user.id)
    if not found:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vendor tool not found"
        )
    await db.commit()
    return None


# ── Catalog (any authenticated user) ─────────────────────────────────────────


@router.get("/catalog", response_model=CatalogResponse)
async def get_catalog(
    q: str | None = None,
    top_k: int = 5,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Access-filtered catalog. With ``q``, returns semantic-ranked top-K tools."""
    if top_k < 1:
        top_k = 1
    if top_k > 50:
        top_k = 50

    if q and q.strip():
        tools = await get_authorized_vendor_catalog_semantic(
            db, user=user, query=q.strip(), top_k=top_k
        )
    else:
        tools = await get_authorized_vendor_catalog(db, user=user)
    entries = [CatalogEntry.model_validate(t) for t in tools]
    return CatalogResponse(tools=entries, count=len(entries))


# ── Tenant grants (admin) ────────────────────────────────────────────────────


@router.post("/grants", response_model=GrantResponse)
async def post_grant_resource(
    payload: GrantTenantResourceRequest,
    response: Response,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    try:
        grant, created = await grant_resource(db, data=payload, actor_id=user.id)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(grant)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return grant


# ── AI Compiler (any authenticated user; access-filtered inside compile) ─────


@router.post("/agents/compile", response_model=CompiledAgentSpec)
async def compile_agent_endpoint(
    payload: CompileAgentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compile a natural-language request into a validated agent DAG spec."""
    spec = await compile_agent(db, user=user, query=payload.query, top_k=payload.top_k)
    return spec


@router.post("/agents/run", response_model=RunAgentResponse)
async def run_agent_endpoint(
    payload: RunAgentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compile and execute a natural-language request via LangGraph."""
    spec = await compile_agent(db, user=user, query=payload.query, top_k=payload.top_k)
    execution = await execute_spec(db, spec)
    return RunAgentResponse(
        spec=spec,
        results=execution.get("results", {}),
        trace=execution.get("trace", []),
    )


# ── Delete / revoke (admin) ──────────────────────────────────────────────────


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor_tool(
    tool_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_tool(db, tool_id=tool_id, actor_id=user.id)
    if not deleted:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vendor tool not found"
        )
    await db.commit()
    return None