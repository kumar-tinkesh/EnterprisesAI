"""OAuth 2.0 Configuration, Authorization consent URL builder, and Redirect Callback landing page."""
from __future__ import annotations

import html
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.backend.config import get_backend_settings

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor.api.v1.schemas import (
    MCPServerResponse,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthConfigRequest,
)
from vendor.services import mcp_auth, oauth_flow
from vendor.services.mcp_service import get_mcp_server

logger = logging.getLogger("vendor.oauth")

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


@router.patch("/mcp/{server_id}/oauth-config", response_model=MCPServerResponse)
async def set_mcp_oauth_config(
    server_id: str,
    payload: OAuthConfigRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Manually set a server's OAuth endpoints (authorization/token URL)."""
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
    """Step 1 of "Connect via OAuth": build the provider's consent URL."""
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
    """Render the callback landing page."""
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
    """Step 2 of "Connect via OAuth": the provider redirects the admin's browser here after consent."""
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
