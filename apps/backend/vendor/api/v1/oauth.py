"""OAuth 2.0 Configuration, Authorization consent URL builder, and Redirect Callback landing page."""
from __future__ import annotations

import html
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
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
    if payload.client_id and payload.client_secret:
        # Save once, encrypted, on the vendor's shared credential row so
        # both the admin's own future authorize calls and every
        # end-user's authorize-as-user call can reuse them without the
        # app secret ever being re-typed or shown to an end-user.
        await mcp_auth.store_server_credentials(
            db,
            server_id=server.id,
            credentials={
                "oauth_client_id": payload.client_id,
                "oauth_client_secret": payload.client_secret,
            },
            tenant_id=None,
        )
    await db.commit()
    await db.refresh(server)
    return server


class InstagramSignInIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=64)
    # Empty keeps the saved one.
    app_secret: str = Field(default="", max_length=128)
    config_id: str = Field(min_length=1, max_length=64)


class InstagramSignInOut(BaseModel):
    app_id: str | None
    config_id: str | None
    has_secret: bool
    ready: bool
    # Register this in the Meta app's login configuration (Redirect URL); Meta only accepts https.
    redirect_uri: str
    redirect_is_https: bool


def _instagram_out(server) -> InstagramSignInOut:
    from vendor.services.mcp_auth import instagram

    setup = instagram.sign_in_setup(server)
    redirect_uri = oauth_flow.callback_redirect_uri(get_backend_settings().BACKEND_PUBLIC_URL)
    return InstagramSignInOut(
        app_id=setup.get("app_id"), config_id=setup.get("config_id"), has_secret=bool(setup.get("has_secret")),
        ready=instagram.sign_in_ready(server), redirect_uri=redirect_uri, redirect_is_https=redirect_uri.startswith("https://"),
    )


async def _instagram_server(db: AsyncSession, server_id: str):
    from vendor.services.mcp_auth import instagram

    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    if not instagram.is_instagram(server):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This isn't the Instagram server.")
    instagram.apply_profile(server)
    return server


@router.get("/mcp/{server_id}/instagram-sign-in", response_model=InstagramSignInOut)
async def get_instagram_sign_in(server_id: str, user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    """The Meta app behind "Connect with Instagram" (never its secret) and the callback URL to register."""
    return _instagram_out(await _instagram_server(db, server_id))


@router.put("/mcp/{server_id}/instagram-sign-in", response_model=InstagramSignInOut)
async def set_instagram_sign_in(
    server_id: str, payload: InstagramSignInIn, user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)
):
    """Save the Meta app (ID, secret, Instagram login configuration) people's "Connect with Instagram" uses."""
    from vendor.services.mcp_auth import instagram

    server = await _instagram_server(db, server_id)
    stored = await mcp_auth.load_server_credentials(db, server_id=server.id, tenant_id=None)
    secret = payload.app_secret.strip() or stored.get(instagram.APP_SECRET, "")
    if not secret:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Add the Meta app's secret.")
    # Merged into the shared row, so the admin's own test token stays.
    await mcp_auth.store_server_credentials(
        db, server_id=server.id, tenant_id=None,
        credentials={**stored, instagram.APP_ID: payload.app_id.strip(), instagram.APP_SECRET: secret},
    )
    server.auth_config = {
        **(server.auth_config or {}),
        "instagram": {"app_id": payload.app_id.strip(), "config_id": payload.config_id.strip(), "has_secret": True},
    }
    await db.commit()
    await db.refresh(server)
    return _instagram_out(server)


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
    backend_public_url = get_backend_settings().BACKEND_PUBLIC_URL
    try:
        if not (payload.client_id and payload.client_secret):
            await oauth_flow.prepare_server(db, server=server, backend_public_url=backend_public_url)
            await db.commit()
        client_id, client_secret = await oauth_flow.resolve_app_credentials(
            db,
            server_id=server.id,
            override_client_id=payload.client_id,
            override_client_secret=payload.client_secret,
            server=server,
        )
        url, state = oauth_flow.build_authorize_url(
            server,
            client_id=client_id,
            client_secret=client_secret,
            backend_public_url=backend_public_url,
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
        server, credentials, tenant_id, user_id = await oauth_flow.complete_authorization(
            db, state=state, code=code, extra_callback_params=params
        )
        await mcp_auth.store_server_credentials(
            db, server_id=server.id, credentials=credentials, tenant_id=tenant_id, user_id=user_id
        )
        await db.commit()
    except oauth_flow.OAuthFlowError as exc:
        await db.rollback()
        return HTMLResponse(
            _oauth_result_html(success=False, message=str(exc)), status_code=400
        )
    username = credentials.get("IG_USERNAME")
    return HTMLResponse(
        _oauth_result_html(
            success=True,
            message=(
                f"Connected as @{username}." if username
                else f"'{server.name}' is now authorized. Click Test/Connect on it to discover tools."
            ),
            server_id=server.id,
        )
    )
