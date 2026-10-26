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
* **Servers that follow the MCP auth spec need no OAuth app at all.** A
  remote server (Atlassian's, …) advertises its authorization server via
  RFC 9728; ``prepare_server`` registers a client there itself (RFC 7591,
  once per callback URL), and the sign-in uses PKCE (RFC 7636) plus the
  RFC 8707 ``resource`` — so neither the admin nor anyone else types a
  client ID or secret.
"""
from __future__ import annotations

import base64
import hashlib
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
    # PKCE (RFC 7636): sent with the code, proves this backend started the sign-in.
    code_verifier: Optional[str] = None
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


def _registered_client(server: VendorMCPServer) -> dict:
    return ((server.auth_config or {}).get("oauth") or {}).get("registered_client") or {}


async def _discover(server: VendorMCPServer) -> dict:
    """OAuth metadata for a remote server registered before discovery kept it (mcp_detect)."""
    from vendor.services import mcp_service

    url = server.endpoint or server.server_url or ""
    if not url.startswith(("http://", "https://")):
        return {}
    try:
        detection = await mcp_service.detect_mcp_server(url)
    except Exception as exc:  # noqa: BLE001 — an unreachable server just stays unconfigured
        logger.warning("OAuth discovery failed for %s: %s", url, exc)
        return {}
    return detection.get("oauth") or {}


async def _register_client(oauth: dict, *, server_name: str, redirect_uri: str) -> dict[str, str]:
    """RFC 7591: register this backend as a sign-in (authorization_code) client."""
    payload = {
        "client_name": f"{server_name or 'MCP'} connector",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        # A public client: PKCE stands in for the secret; a server that insists on one still returns it.
        "token_endpoint_auth_method": "none",
    }
    if oauth.get("scopes_supported"):
        payload["scope"] = " ".join(oauth["scopes_supported"])
    try:
        async with mcp_auth._new_client() as client:
            response = await client.post(oauth["registration_endpoint"], json=payload)
    except httpx.HTTPError as exc:
        raise OAuthFlowError(f"Could not reach the client registration endpoint: {exc}") from exc
    if response.status_code not in (200, 201):
        raise OAuthFlowError(
            f"Client registration failed ({response.status_code}): {response.text[:200]}"
        )
    body = response.json()
    if not body.get("client_id"):
        raise OAuthFlowError("Client registration response is missing client_id.")
    # Honour the method the server settled on: a "none" client sends no secret even if one came back.
    public = body.get("token_endpoint_auth_method", "none") == "none"
    return {"client_id": body["client_id"], "client_secret": "" if public else body.get("client_secret") or ""}


async def prepare_server(db: AsyncSession, *, server: VendorMCPServer, backend_public_url: str) -> None:
    """Make a server ready for "Connect via OAuth" without anyone typing an OAuth app:
    discover its endpoints if they were never saved, and register a client with its
    authorization server (RFC 7591) when it offers that and none is registered for
    this callback URL yet. Does nothing for servers set up by hand. Flushes; the
    caller commits."""
    auth_config = dict(server.auth_config or {})
    oauth = dict(auth_config.get("oauth") or {})
    if not oauth.get("authorization_endpoint") and server.source_type == "remote":
        oauth = {**await _discover(server), **{k: v for k, v in oauth.items() if v}}
    if not (oauth.get("authorization_endpoint") and oauth.get("registration_endpoint")):
        return
    stored = await mcp_auth.load_server_credentials(db, server_id=server.id, tenant_id=None)
    redirect_uri = callback_redirect_uri(backend_public_url)
    registered = oauth.get("registered_client") or {}
    if stored.get("oauth_client_id") and registered.get("client_id") != stored["oauth_client_id"]:
        return  # an OAuth app the admin configured themselves wins
    if not registered.get("client_id") or registered.get("redirect_uri") != redirect_uri:
        # First sign-in, or the callback URL moved (a new ngrok address): the old client can't redirect here.
        client = await _register_client(oauth, server_name=server.name, redirect_uri=redirect_uri)
        oauth["registered_client"] = {"client_id": client["client_id"], "redirect_uri": redirect_uri}
        await mcp_auth.store_server_credentials(
            db,
            server_id=server.id,
            credentials={**stored, "oauth_client_id": client["client_id"], "oauth_client_secret": client["client_secret"]},
            tenant_id=None,
        )
    auth_config["oauth"] = oauth
    server.auth_config = auth_config
    await db.flush()


async def resolve_app_credentials(
    db: AsyncSession,
    *,
    server_id: str,
    override_client_id: Optional[str] = None,
    override_client_secret: Optional[str] = None,
    server: Optional[VendorMCPServer] = None,
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
    # A client prepare_server registered may be public (no secret): PKCE covers it.
    registered = server is not None and client_id and _registered_client(server).get("client_id") == client_id
    if registered:
        return client_id, client_secret or ""
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
    # PKCE whenever the provider advertises it, and always for a client without a secret.
    code_verifier = None
    if "S256" in (oauth.get("code_challenge_methods_supported") or []) or not client_secret:
        code_verifier = secrets.token_urlsafe(64)
    _pending[state] = _PendingAuthorization(
        server_id=server.id,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        user_id=user_id,
        code_verifier=code_verifier,
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
    if code_verifier:
        digest = hashlib.sha256(code_verifier.encode()).digest()
        params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        params["code_challenge_method"] = "S256"
    if oauth.get("resource"):
        params["resource"] = oauth["resource"]

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
        pkce = {"code_verifier": pending.code_verifier} if pending.code_verifier else {}
        token_response = await mcp_auth.exchange_authorization_code(
            oauth, credentials, code=code, redirect_uri=pending.redirect_uri, **pkce
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
    if pending.user_id is None:
        # The admin's own sign-in replaces the shared row: keep the OAuth app on it, so people's
        # authorize-as-user (resolve_app_credentials) works without a separate oauth-config call.
        merged["oauth_client_id"] = pending.client_id
        merged["oauth_client_secret"] = pending.client_secret

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
    "prepare_server",
    "resolve_app_credentials",
    "build_authorize_url",
    "complete_authorization",
]
