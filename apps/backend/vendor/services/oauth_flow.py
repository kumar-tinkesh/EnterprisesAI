"""Generic OAuth2 authorization-code ("Connect via OAuth") flow.

This is the human-consent bootstrap step that ``mcp_auth._resolve_oauth2``
doesn't cover: for a provider that requires an interactive login + consent
screen (QuickBooks, Notion's OAuth apps, Slack, …), there is no way to get
an initial refresh_token except by sending the admin's browser through the
provider's own authorize page. Once that has happened once per server, the
resulting refresh_token is stored like any other credential and every
future call goes through the already-implemented refresh_token grant in
``mcp_auth._resolve_oauth2`` — this module is only the one-time bootstrap.

Design notes (why this works for ANY provider, not just one):

* **One shared callback URL for every server.** Providers require an exact,
  pre-registered redirect_uri, and re-registering a new one per MCP server
  (they're created with random UUIDs) isn't realistic. So there is exactly
  one fixed callback path (see ``callback_redirect_uri``); the ``state``
  parameter — opaque, round-tripped unmodified by every OAuth provider by
  spec — carries which server/tenant this particular flow belongs to. The
  admin registers this one URL once per provider console, not once per
  server.
* **No provider-specific field names.** A provider may tack extra fields
  onto its callback beyond the standard ``code``/``state`` (Intuit sends
  ``realmId``; another provider might send ``team_id`` or ``shop``). These
  are captured generically as extra query params and fuzzy-matched against
  this *server's own* detected credential field names (see
  ``_match_declared_field``) rather than hardcoded per vendor.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from vendor.models import VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.mcp_service import get_mcp_server

logger = logging.getLogger("vendor.oauth_flow")

_PENDING_TTL_SECONDS = 600  # 10 minutes — long enough to complete a login+consent screen


@dataclass
class _PendingAuthorization:
    server_id: str
    tenant_id: Optional[str]
    client_id: str
    client_secret: str
    redirect_uri: str
    # Set only when an end-user (not the vendor admin) started this flow —
    # see ``build_authorize_url``'s ``user_id`` param. Determines whether
    # the callback persists the resulting tokens as the vendor's shared
    # primary credential or as this one user's isolated row.
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)


# In-memory, keyed by the random `state` value — same convention as this
# package's other short-lived caches (catalog_engine._ANALYSIS_CACHE,
# mcp_auth._token_cache). A single-process store is fine here: a pending
# authorization is only ever redeemed once, by the same browser, within
# minutes of being created.
_pending: dict[str, _PendingAuthorization] = {}


class OAuthFlowError(Exception):
    """Raised for any failure in the authorize/callback bootstrap flow."""


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [
        state
        for state, entry in _pending.items()
        if now - entry.created_at > _PENDING_TTL_SECONDS
    ]
    for state in expired:
        _pending.pop(state, None)


def callback_redirect_uri(backend_public_url: str) -> str:
    """The one fixed, shared callback URL every provider console registers."""
    return f"{backend_public_url.rstrip('/')}/api/v1/vendor/resources/mcp/oauth/callback"


async def resolve_app_credentials(
    db: AsyncSession,
    *,
    server_id: str,
    override_client_id: Optional[str] = None,
    override_client_secret: Optional[str] = None,
) -> tuple[str, str]:
    """Resolve the OAuth app's (client_id, client_secret) for a server.

    Explicit overrides win (the vendor admin's own authorize call may still
    pass them ad hoc). Otherwise falls back to whatever was saved via
    ``PATCH .../oauth-config`` — stored encrypted in the server's shared
    credential row (``tenant_id=None, user_id=None``) under
    ``oauth_client_id``/``oauth_client_secret``. This is the only source
    available to an end-user's ``authorize-as-user`` call, which never
    accepts the app secret directly.
    """
    if override_client_id and override_client_secret:
        return override_client_id, override_client_secret

    stored = await mcp_auth.load_server_credentials(db, server_id=server_id, tenant_id=None)
    client_id = override_client_id or stored.get("oauth_client_id")
    client_secret = override_client_secret or stored.get("oauth_client_secret")
    if not client_id or not client_secret:
        raise OAuthFlowError(
            "No OAuth client_id/client_secret configured for this server. "
            "A vendor admin must set them via PATCH /mcp/{server_id}/oauth-config first."
        )
    return client_id, client_secret


def build_authorize_url(
    server: VendorMCPServer,
    *,
    client_id: str,
    client_secret: str,
    backend_public_url: str,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    scope_override: Optional[str] = None,
) -> tuple[str, str]:
    """Return ``(authorization_url, state)`` for the given server.

    Raises :class:`OAuthFlowError` if the server has no known
    ``authorization_endpoint`` — that happens for servers whose OAuth
    metadata was never discovered (e.g. a local stdio server that isn't
    running yet at analysis time); use ``PATCH /mcp/{id}/oauth-config`` to
    supply it manually first (Intuit's, Slack's, etc. authorize/token URLs
    are fixed and documented, not something a repo scan can discover).
    """
    oauth = (server.auth_config or {}).get("oauth") or {}
    authorization_endpoint = oauth.get("authorization_endpoint")
    if not authorization_endpoint:
        raise OAuthFlowError(
            "This server has no known authorization_endpoint. Set one via "
            "PATCH /mcp/{server_id}/oauth-config first."
        )
    if not oauth.get("token_endpoint"):
        raise OAuthFlowError(
            "This server has no known token_endpoint. Set one via "
            "PATCH /mcp/{server_id}/oauth-config first."
        )

    _purge_expired()
    state = secrets.token_urlsafe(32)
    redirect_uri = callback_redirect_uri(backend_public_url)
    _pending[state] = _PendingAuthorization(
        server_id=server.id,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        user_id=user_id,
    )

    scope = scope_override or " ".join(oauth.get("scopes_supported") or [])
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        **(oauth.get("extra_authorize_params") or {}),
    }
    if scope:
        params["scope"] = scope

    return f"{authorization_endpoint}?{urlencode(params)}", state


def _match_declared_field(param_name: str, declared_field_names: list[str]) -> Optional[str]:
    """Fold away case/underscores and match a provider's own callback param
    name (e.g. Intuit's camelCase ``realmId``) against this server's
    *detected* credential field names (e.g. ``QUICKBOOKS_REALM_ID``) — every
    provider invents its own param naming, so this is a normalization rule,
    not a per-vendor lookup table."""
    folded_param = param_name.replace("_", "").lower()
    for name in declared_field_names:
        if name.replace("_", "").lower().endswith(folded_param):
            return name
    return None


async def complete_authorization(
    db: AsyncSession,
    *,
    state: str,
    code: str,
    extra_callback_params: dict[str, str],
) -> tuple[VendorMCPServer, dict[str, str], Optional[str], Optional[str]]:
    """Redeem ``code`` for tokens against whichever server ``state`` was
    issued for. Returns ``(server, credentials_to_persist, tenant_id,
    user_id)`` — the last two say *who* this flow belongs to (both ``None``
    for the vendor admin's own shared authorization; ``user_id`` set when
    an end-user started it via ``authorize-as-user``) so the caller can
    persist to the right row via ``mcp_auth.store_server_credentials``.
    This function only reads; callers persist and commit alongside whatever
    else they're doing in the same request.

    The path has no ``{server_id}`` (see module docstring — one shared
    callback URL for every server), so ``state`` is how we find it.

    Raises :class:`OAuthFlowError` on an invalid/expired state, a server
    that's since been deleted, or a failed token exchange.
    """
    _purge_expired()
    pending = _pending.pop(state, None)
    if pending is None:
        raise OAuthFlowError("Unknown or expired authorization state.")

    server = await get_mcp_server(db, server_id=pending.server_id)
    if server is None:
        raise OAuthFlowError("The MCP server for this authorization no longer exists.")

    oauth = (server.auth_config or {}).get("oauth") or {}
    if not oauth.get("token_endpoint"):
        raise OAuthFlowError("This server has no known token_endpoint.")

    credentials = {"client_id": pending.client_id, "client_secret": pending.client_secret}
    try:
        token_response = await mcp_auth.exchange_authorization_code(
            oauth, credentials, code=code, redirect_uri=pending.redirect_uri
        )
    except mcp_auth.McpAuthError as exc:
        raise OAuthFlowError(f"Token exchange failed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OAuthFlowError(f"Could not reach token endpoint: {exc}") from exc

    merged: dict[str, str] = {
        **credentials,
        "access_token": token_response["access_token"],
    }
    if token_response.get("refresh_token"):
        merged["refresh_token"] = token_response["refresh_token"]

    declared_field_names = [
        f.get("name", "") for f in ((server.auth_schema or {}).get("fields") or [])
    ]
    for param_name, value in extra_callback_params.items():
        if param_name in ("code", "state") or not value:
            continue
        merged[param_name] = value
        matched = _match_declared_field(param_name, declared_field_names)
        if matched and matched not in merged:
            merged[matched] = value

    return server, merged, pending.tenant_id, pending.user_id


__all__ = [
    "OAuthFlowError",
    "callback_redirect_uri",
    "resolve_app_credentials",
    "build_authorize_url",
    "complete_authorization",
]
