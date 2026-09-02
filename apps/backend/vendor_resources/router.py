"""FastAPI REST endpoints for the Vendor Resources subsystem (MCP only).

All routes reuse the Auth service's auth/RBAC dependencies via absolute imports
(``src.api.deps``, ``src.core.roles``, ``src.db.session``) — no duplicate auth
code. The router is mounted by ``apps.backend.main`` under
``/api/v1/vendor/resources``.

Routes (Phase 1):
    POST   /mcp        vendor_admin  register an MCP server
    GET    /mcp        vendor_admin  list all MCP servers
    GET    /catalog    any user      access-filtered authorised catalog
    POST   /grants     vendor_admin  grant a resource to a tenant
    DELETE /{id}       vendor_admin  delete an MCP server (cascades grants)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor_resources.schemas import (
    AnalyzeRepoRequest,
    AnalyzeRepoResponse,
    CatalogEntry,
    CatalogResponse,
    ConnectMCPServerRequest,
    ConnectCredentialsRequest,
    ConnectMCPServerResponse,
    GrantResponse,
    GrantTenantResourceRequest,
    McpDetectRequest,
    McpDetectResponse,
    MCPServerResponse,
)
from vendor_resources.services.catalog_engine import (
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
)
from vendor_resources.services.mcp_auth import McpAuthError
from vendor_resources.services.mcp_client import connect_mcp_server
from vendor_resources.services.mcp_detect import McpDetectError, detect_mcp_server
from vendor_resources.services.mcp_service import (
    connect_registered_server,
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    grant_resource,
    list_mcp_servers,
)
from vendor_resources.services.repo_analyzer import analyze_repo

logger = logging.getLogger("vendor_resources.router")

router = APIRouter()

_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


# ── MCP server management (admin) ────────────────────────────


@router.post(
    "/mcp",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_create_mcp_server(
    payload: ConnectMCPServerRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    server = await create_mcp_server(db, data=payload, actor_id=user.id)
    await db.commit()
    await db.refresh(server)
    return server


@router.get("/mcp", response_model=list[MCPServerResponse])
async def get_list_mcp_servers(
    _user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    return await list_mcp_servers(db)


@router.post("/mcp/{server_id}/embed", status_code=status.HTTP_204_NO_CONTENT)
async def embed_mcp_server(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """(Re)compute a server's semantic embedding (admin)."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await db.commit()
    return None


@router.post("/mcp/detect", response_model=McpDetectResponse)
async def detect_mcp_server_endpoint(
    payload: McpDetectRequest,
    _user: CurrentUser = _admin,
):
    """Natively probe any MCP URL/command and report which credential type it
    wants (none / api_key / bearer / basic / oauth2) before connecting.

    For http(s) URLs the backend sends an unauthenticated MCP ``initialize``
    probe, parses ``WWW-Authenticate`` challenges, and checks the RFC 9728 /
    RFC 8414 OAuth well-known metadata endpoints. Nothing is guessed from
    URL patterns — every classification comes from what the server itself
    advertises. Non-URL input is classified as a stdio command.
    """
    try:
        result = await detect_mcp_server(payload.server_url)
    except McpDetectError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post("/mcp/{server_id}/connect", response_model=ConnectMCPServerResponse)
async def connect_mcp_server_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest | None = None,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Test connection and return discovered transport + tools.

    Auth is resolved natively: stored encrypted credentials (vendor-level or
    per-tenant) are merged with any credentials supplied in the request, then
    ``mcp_auth`` builds the headers the server's detected auth type calls for
    — including native OAuth2 token acquisition/refresh. Raw header maps are
    still accepted for backward compatibility.
    """
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    try:
        creds = payload.credentials if payload is not None else None
        result = await connect_registered_server(
            db, server=server, request_credentials=creds
        )
        await db.commit()  # persist any rotated OAuth tokens / dynamic registrations
    except McpAuthError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential resolution failed: {exc}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to connect MCP server %s", server_id)
        
        # Unpack BaseExceptionGroup (Python 3.11+) to extract root cause
        err_msg = str(exc)
        if isinstance(exc, BaseExceptionGroup):
            sub_msgs = []
            for sub in exc.exceptions:
                if isinstance(sub, BaseExceptionGroup):
                    sub_msgs.extend([str(s) for s in sub.exceptions])
                else:
                    sub_msgs.append(str(sub))
            err_msg = " | ".join(sub_msgs)

        if "Connection closed" in err_msg or "MCPError" in err_msg:
            err_msg = "MCP server process exited (connection closed). Please verify primary credentials and server command."

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Connection failed: {err_msg}",
        ) from exc
    return ConnectMCPServerResponse(**result)


# ── Catalog (any authenticated user) ─────────────────────────────────


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


# ── New MCP repo analyzer (admin) ────────────────────────────


@router.post(
    "/mcp/analyze-repo",
    response_model=AnalyzeRepoResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_mcp_repo_endpoint(
    payload: AnalyzeRepoRequest,
    _user: CurrentUser = _admin,
):
    """Analyze a GitHub repository or direct endpoint for MCP characteristics.

    Determines transport type (stdio, docker, streamable_http, sse),
    runtime environment, suggested startup command, remote endpoint,
    required environment variables, and authentication type.

    Zero hardcoded vendor rules — all detection is runtime heuristic-based.
    """
    try:
        result = await analyze_repo(payload.repo_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository analysis failed: {str(exc)}",
        ) from exc
    return result


# ── Tenant grants (admin) ────────────────────────────────────


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


# ── Delete / revoke (admin) ──────────────────────────────────


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server_endpoint(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_mcp_server(db, server_id=server_id, actor_id=user.id)
    if not deleted:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await db.commit()
    return None