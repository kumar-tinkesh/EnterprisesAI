"""FastAPI REST endpoints for the Vendor Resources subsystem (MCP only).

All routes reuse the Auth service's auth/RBAC dependencies via absolute imports
(``src.api.deps``, ``src.core.roles``, ``src.db.session``) — no duplicate auth
code. The router is mounted by ``apps.backend.main`` under
``/api/v1/vendor/resources``.

Routes:
    POST   /mcp                    vendor_admin  Step 1: Add MCP server (analyze + register, UNCONNECTED)
    POST   /mcp/{server_id}/test   vendor_admin  Step 2: Test connection & discover tools (VERIFIED)
    GET    /mcp                    vendor_admin  List all MCP servers
    GET    /catalog                any user      Access-filtered authorised catalog
    GET    /catalog/tools          any user      Two-stage semantic tool search (query -> servers -> tools)
    GET    /catalog/plan-tool-call any user      Select one tool + fill its arguments via LLM (no invocation)
    POST   /grants                 vendor_admin  Grant a resource to a tenant
    DELETE /{id}                   vendor_admin  Delete an MCP server (cascades grants)
    POST   /mcp/detect             vendor_admin  Probe MCP URL for transport/auth (pre-add analysis)
    POST   /mcp/analyze-repo       vendor_admin  Analyze GitHub repo/URL for MCP characteristics
    PATCH  /mcp/{id}/oauth-config      vendor_admin  Manually set OAuth authorize/token endpoints
    POST   /mcp/{id}/oauth/authorize  vendor_admin  Build the provider consent URL ("Connect via OAuth")
    GET    /mcp/oauth/callback        public         Provider redirects here after consent (state-scoped)
"""
from __future__ import annotations

import html
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.backend.config import get_backend_settings

from src.api.deps import CurrentUser, get_current_user, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor_resources.schemas import (
    AddMCPServerRequest,
    AddMCPServerResponse,
    AnalyzeRepoRequest,
    AnalyzeRepoResponse,
    CatalogEntry,
    CatalogResponse,
    ConnectCredentialsRequest,
    ConnectMCPServerRequest,
    ConnectMCPServerResponse,
    GrantResponse,
    GrantTenantResourceRequest,
    McpDetectRequest,
    McpDetectResponse,
    MCPServerResponse,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthConfigRequest,
    PlannedToolCall,
    ToolCallPlanResponse,
    ToolSearchResponse,
    ToolSearchResult,
)
from vendor_resources.models import MCPTool
from vendor_resources.services import mcp_auth, oauth_flow
from vendor_resources.services.catalog_engine import (
    embed_server,
    embed_tool,
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
    get_relevant_tools_semantic,
)
from vendor_resources.services.tool_call_planner import plan_tool_call
from vendor_resources.services.mcp_auth import McpAuthError
from vendor_resources.services.mcp_client import connect_mcp_server
from vendor_resources.services.mcp_detect import McpDetectError, detect_mcp_server
from vendor_resources.services.mcp_service import (
    add_mcp_server,
    test_mcp_connection,
    connect_registered_server,
    disconnect_mcp_server,
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

# Step 1: Add MCP Server (Register only — no connection)
@router.post(
    "/mcp",
    response_model=AddMCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_add_mcp_server(
    payload: AddMCPServerRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Step 1: Add an MCP server from a Remote MCP URL or GitHub/Source repository URL.

    Analyzes the source, detects transport/runtime/auth, builds normalized config,
    and saves the server with status=UNCONNECTED. Does NOT attempt connection
    if credentials are missing (per architecture Rule 7).
    """
    server = await add_mcp_server(db, data=payload, actor_id=user.id)
    await db.commit()
    await db.refresh(server)
    return server


# Legacy endpoint (kept for backward compatibility)
@router.post(
    "/mcp/legacy",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_create_mcp_server_legacy(
    payload: ConnectMCPServerRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Legacy: Register an MCP server with optional immediate connection.

    New code should use POST /mcp (Step 1) then POST /mcp/{id}/test (Step 2).
    """
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
    """(Re)compute a server's semantic embedding, and its tools' (admin).

    Useful after switching the configured embedding provider/model, or if a
    prior embed attempt failed (e.g. provider outage) at add/test time.
    """
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await embed_server(server)
    tools = (
        await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server.id))
    ).scalars().all()
    for tool in tools:
        await embed_tool(tool)
    await db.commit()
    return None


# Step 2: Test Connection & Discover Tools
@router.post(
    "/mcp/{server_id}/test",
    response_model=ConnectMCPServerResponse,
)
async def test_mcp_connection_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest | None = None,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Test connection and discover tools for a registered MCP server.

    User provides credentials via dynamic form (from server.auth_schema).
    Connects via generic MCPClient, runs initialize + tools/list,
    saves discovered tools, updates status to VERIFIED.
    """
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    if server.status == "VERIFIED":
        # Already verified — return current tools
        return ConnectMCPServerResponse(
            transport=getattr(server, "transport", "stdio"),
            bound_tools=server.bound_tools,
            tools=[],  # Could fetch full tool details if needed
            auth_type=server.auth_type or "none",
            status="VERIFIED",
        )
    try:
        creds = payload.credentials if payload is not None else None
        result = await test_mcp_connection(
            db, server=server, request_credentials=creds, tenant_id=user.id
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
        logger.exception("Failed to test MCP server %s", server_id)

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


# Legacy connect endpoint (kept for backward compatibility)
@router.post("/mcp/{server_id}/connect", response_model=ConnectMCPServerResponse)
async def connect_mcp_server_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest | None = None,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Legacy: Test connection and return discovered transport + tools.

    New code should use POST /mcp/{server_id}/test (Step 2).
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


@router.post("/mcp/{server_id}/disconnect", response_model=MCPServerResponse)
async def disconnect_mcp_server_endpoint(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Disconnect an MCP server: reset status to UNCONNECTED and clear stored credentials."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    updated = await disconnect_mcp_server(db, server=server)
    await db.commit()
    await db.refresh(updated)
    return updated


# ── OAuth "Connect via provider" bootstrap (admin to start, provider to finish) ──
#
# Generic authorization_code flow for servers a plain credential form can't
# bootstrap alone (the admin has client_id/client_secret from the provider's
# console, but no way to get an initial refresh_token without an interactive
# consent screen). See vendor_resources.services.oauth_flow for how this
# stays generic across every provider (one shared callback URL; state
# carries which server; extra callback params are matched generically).


@router.patch("/mcp/{server_id}/oauth-config", response_model=MCPServerResponse)
async def set_mcp_oauth_config(
    server_id: str,
    payload: OAuthConfigRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Manually set a server's OAuth endpoints (authorization/token URL).

    Needed before "Connect via OAuth" will work for a server whose metadata
    couldn't be auto-discovered (a local stdio server isn't running yet at
    analysis time, so there's nothing to probe). Most providers publish
    these as fixed, documented URLs — this is a one-time admin paste per
    server, not code.
    """
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    auth_config = dict(server.auth_config or {})
    auth_config["oauth"] = {
        "authorization_endpoint": payload.authorization_endpoint,
        "token_endpoint": payload.token_endpoint,
        "scopes_supported": payload.scope.split() if payload.scope else [],
        "extra_authorize_params": payload.extra_authorize_params or {},
    }
    server.auth_config = auth_config
    server.auth_type = "oauth2"
    await db.commit()
    await db.refresh(server)
    return server


@router.post("/mcp/{server_id}/oauth/authorize", response_model=OAuthAuthorizeResponse)
async def start_mcp_oauth_authorize(
    server_id: str,
    payload: OAuthAuthorizeRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Step 1 of "Connect via OAuth": build the provider's consent URL.

    The frontend sends the admin's browser to ``authorization_url`` (full
    redirect or a popup); the provider redirects back to the one shared
    callback below, which finishes the exchange.
    """
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    try:
        url, state = oauth_flow.build_authorize_url(
            server,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            backend_public_url=get_backend_settings().BACKEND_PUBLIC_URL,
            scope_override=payload.scope,
        )
    except oauth_flow.OAuthFlowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return OAuthAuthorizeResponse(authorization_url=url, state=state)


def _oauth_result_html(*, success: bool, message: str, server_id: str | None = None) -> str:
    """Render the callback landing page. Also posts a ``message`` event to
    ``window.opener`` (the admin dashboard tab that opened this as a popup)
    so it can auto-refresh without the admin manually clicking back and
    forth — every value is escaped/JSON-encoded since ``message`` may
    originate from the OAuth provider's own redirect (e.g. its
    ``error_description``), not just our own code.
    """
    safe_message = html.escape(message)
    event_type = "MCP_OAUTH_SUCCESS" if success else "MCP_OAUTH_ERROR"
    payload = json.dumps({"type": event_type, "serverId": server_id, "message": message})
    heading = "Connected" if success else "Connection failed"
    footer = (
        "This tab will close automatically."
        if success
        else 'Close this tab and try "Connect via OAuth" again from the dashboard.'
    )
    auto_close = "setTimeout(function () { window.close(); }, 1200);" if success else ""
    return f"""
<html><body style="font-family:sans-serif;text-align:center;padding:4rem">
<h2>{heading}</h2>
<p>{safe_message}</p>
<p>{footer}</p>
<script>
  if (window.opener) {{
    window.opener.postMessage({payload}, "*");
    {auto_close}
  }}
</script>
</body></html>
"""


@router.get("/mcp/oauth/callback", response_class=HTMLResponse)
async def mcp_oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Step 2 of "Connect via OAuth": the provider redirects the admin's
    browser here after consent. Unauthenticated by design — the provider
    itself is the caller, not our SPA — ``state`` is what proves this
    belongs to a flow we started (see ``oauth_flow.build_authorize_url``).

    One fixed path for every server (no ``{server_id}`` — see
    ``oauth_flow`` module docstring for why); ``state`` carries which
    server this belongs to.
    """
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        error = params.get("error_description") or params.get("error") or "Missing code/state."
        return HTMLResponse(_oauth_result_html(success=False, message=error), status_code=400)

    try:
        server, credentials = await oauth_flow.complete_authorization(
            db, state=state, code=code, extra_callback_params=params
        )
        await mcp_auth.store_server_credentials(
            db, server_id=server.id, credentials=credentials, tenant_id=None
        )
        await db.commit()
    except oauth_flow.OAuthFlowError as exc:
        await db.rollback()
        return HTMLResponse(
            _oauth_result_html(success=False, message=str(exc)), status_code=400
        )
    return HTMLResponse(
        _oauth_result_html(
            success=True,
            message=f"'{server.name}' is now authorized. Click Test/Connect on it to discover tools.",
            server_id=server.id,
        )
    )


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