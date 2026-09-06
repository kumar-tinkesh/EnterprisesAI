"""Native, standards-driven MCP credential resolution engine.

Bridges detection (``mcp_detect``) and connection (``mcp_client``): given a
server's detected ``auth_config`` and the credentials available for it
(supplied at request time and/or persisted encrypted in the DB), this module
produces ready-to-use HTTP auth headers — acquiring tokens natively where the
server's advertised metadata allows it.

Supported auth types (chosen by what the *server* advertises, never by URL
pattern matching — zero provider-specific code):

- ``none``    → no headers (public / open MCP servers)
- ``env``     → stdio servers; mcp_client injects credentials as env vars
- ``api_key`` → ``X-API-Key: <key>`` (or a caller-specified ``header_name``)
- ``basic``   → ``Authorization: Basic base64(user:pass)``
- ``bearer``  → ``Authorization: Bearer <token>`` (static token / JWT)
- ``oauth2``  → native token acquisition using the OAuth metadata discovered
  at detection time (RFC 8414/9728, stored in ``auth_config["oauth"]``):
    1. cached token (refreshed ``_TOKEN_EXPIRY_MARGIN`` seconds before expiry)
    2. ``refresh_token`` grant (rotated refresh tokens are re-persisted)
    3. ``client_credentials`` grant (client_id + client_secret)
    4. RFC 7591 dynamic client registration → ``client_credentials``
    5. passthrough of a pre-obtained ``access_token`` (e.g. a JWT)
- unknown     → raw auth-header passthrough (legacy behaviour)

Credentials are stored Fernet-encrypted (PBKDF2-derived from the service's
``SECRET_KEY``) in the ``vendor_mcp_credentials`` table, either vendor-level
(``tenant_id IS NULL``) or per-tenant (a tenant row overrides the fallback).
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vendor_resources.models import VendorMCPCredential

logger = logging.getLogger("vendor_resources.mcp_auth")

_DEFAULT_TIMEOUT = 15.0
# Refresh cached tokens this many seconds before their stated expiry.
_TOKEN_EXPIRY_MARGIN = 60.0

# Header names a caller may pass in ``credentials`` verbatim (backward-compat:
# older clients sent a raw header map).
_KNOWN_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token"}

# In-memory token cache: (server_id_or_url, tenant_id) → token entry.
_token_cache: dict[tuple[str, str | None], dict[str, Any]] = {}


class McpAuthError(Exception):
    """Raised when credentials for an auth-protected MCP server cannot be resolved."""


# ── credential encryption (same scheme as apps/auth mcp/credentials.py) ──


def _fernet() -> Fernet:
    from base64 import urlsafe_b64encode

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    from src.config import get_settings

    settings = get_settings()
    # Prefer the dedicated secret; fall back to the (always generated)
    # JWT private key so the deployment needs no extra configuration.
    secret = settings.MCP_CREDENTIALS_SECRET or settings.JWT_PRIVATE_KEY
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mcp_credentials_salt",
        iterations=100_000,
    )
    return Fernet(urlsafe_b64encode(kdf.derive(secret.encode())))


def encrypt_credentials(credentials: dict[str, str]) -> str:
    import json

    return _fernet().encrypt(json.dumps(credentials, sort_keys=True).encode()).decode()


def decrypt_credentials(encrypted: str) -> dict[str, str]:
    import json

    try:
        return json.loads(_fernet().decrypt(encrypted.encode()).decode())
    except Exception as exc:  # noqa: BLE001
        raise McpAuthError(f"Failed to decrypt stored MCP credentials: {exc}") from exc


# ── encrypted credential persistence ─────────────────────────────────


async def store_server_credentials(
    db: AsyncSession,
    *,
    server_id: str,
    credentials: dict[str, str],
    tenant_id: str | None = None,
) -> None:
    """Encrypt and upsert the credential set for a server (optionally per-tenant)."""
    encrypted = encrypt_credentials(credentials)
    row = (
        await db.execute(
            select(VendorMCPCredential).where(
                VendorMCPCredential.server_id == server_id,
                VendorMCPCredential.tenant_id == tenant_id,
            )
        )
    ).scalars().first()
    if row is not None:
        row.encrypted_credentials = encrypted
    else:
        db.add(
            VendorMCPCredential(
                server_id=server_id, tenant_id=tenant_id, encrypted_credentials=encrypted
            )
        )
    await db.flush()


async def load_server_credentials(
    db: AsyncSession, *, server_id: str, tenant_id: str | None = None
) -> dict[str, str]:
    """Decrypt and return stored credentials; per-tenant rows override the
    vendor-level (``tenant_id IS NULL``) fallback."""
    row = (
        await db.execute(
            select(VendorMCPCredential).where(
                VendorMCPCredential.server_id == server_id,
                VendorMCPCredential.tenant_id == tenant_id,
            )
        )
    ).scalars().first()
    if row is None and tenant_id is not None:
        row = (
            await db.execute(
                select(VendorMCPCredential).where(
                    VendorMCPCredential.server_id == server_id,
                    VendorMCPCredential.tenant_id.is_(None),
                )
            )
        ).scalars().first()
    return decrypt_credentials(row.encrypted_credentials) if row else {}


async def delete_server_credentials(db: AsyncSession, *, server_id: str) -> None:
    """Delete every stored credential row (vendor-level and per-tenant)."""
    await db.execute(
        delete(VendorMCPCredential).where(VendorMCPCredential.server_id == server_id)
    )


# ── header builders ──────────────────────────────────────────────────


def _basic_header(credentials: dict[str, str]) -> dict[str, str]:
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _api_key_header(credentials: dict[str, str]) -> dict[str, str]:
    api_key = (
        credentials.get("api_key")
        or credentials.get("api-key")
        or credentials.get("x-api-key")
        or credentials.get("access_token")
        or ""
    )
    if not api_key:
        return {}
    header_name = credentials.get("header_name") or "X-API-Key"
    if header_name.lower() == "authorization":
        return {"Authorization": f"Bearer {api_key}"}
    return {header_name: api_key}


def _bearer_header(token: str) -> dict[str, str]:
    if token.startswith("Bearer "):
        return {"Authorization": token}
    return {"Authorization": f"Bearer {token}"}


def _raw_header_passthrough(credentials: dict[str, str]) -> dict[str, str]:
    return {
        k: v
        for k, v in credentials.items()
        if k.lower() in _KNOWN_AUTH_HEADERS or ":" in k
    }


# ── OAuth2 token acquisition (flows from discovered metadata only) ──


def _new_client() -> httpx.AsyncClient:
    """Client factory — patchable in tests (httpx.MockTransport)."""
    return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)


async def _token_request(
    token_endpoint: str, form: dict[str, str], basic: tuple[str, str] | None = None
) -> dict[str, Any]:
    """POST an OAuth token request (RFC 6749) and return the JSON response."""
    headers = {}
    if basic:
        encoded = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    async with _new_client() as client:
        response = await client.post(token_endpoint, data=form, headers=headers or None)
    if response.status_code != 200:
        raise McpAuthError(
            f"Token endpoint returned {response.status_code}: {response.text[:200]}"
        )
    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        raise McpAuthError(f"Token endpoint returned non-JSON body: {exc}") from exc
    if not body.get("access_token"):
        raise McpAuthError(f"Token endpoint response missing access_token: {body}")
    return body


def _merge_scopes(oauth: dict, credentials: dict[str, str]) -> str:
    scope = credentials.get("scope") or " ".join(oauth.get("scopes_supported") or [])
    return scope.strip()


async def _client_credentials_grant(
    oauth: dict, credentials: dict[str, str]
) -> dict[str, Any]:
    """RFC 6749 §4.4 client_credentials grant (client auth via HTTP Basic)."""
    client_id = credentials.get("client_id", "")
    client_secret = credentials.get("client_secret", "")
    form: dict[str, str] = {"grant_type": "client_credentials"}
    scope = _merge_scopes(oauth, credentials)
    if scope:
        form["scope"] = scope
    return await _token_request(
        oauth["token_endpoint"], form, basic=(client_id, client_secret)
    )


async def _refresh_token_grant(
    oauth: dict, credentials: dict[str, str], refresh_token: str
) -> dict[str, Any]:
    """RFC 6749 §6 refresh_token grant."""
    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    scope = _merge_scopes(oauth, credentials)
    if scope:
        form["scope"] = scope
    basic = None
    if credentials.get("client_id") and credentials.get("client_secret"):
        basic = (credentials["client_id"], credentials["client_secret"])
    return await _token_request(oauth["token_endpoint"], form, basic=basic)


async def exchange_authorization_code(
    oauth: dict, credentials: dict[str, str], *, code: str, redirect_uri: str
) -> dict[str, Any]:
    """RFC 6749 §4.1.3 authorization_code grant.

    This is the one-time human-consent *bootstrap* step (see
    ``vendor_resources.services.oauth_flow`` for the live redirect that
    produces ``code``) — it exchanges the one-time code for the initial
    access_token/refresh_token pair. Every call after this one goes through
    ordinary ``resolve_auth``/``_resolve_oauth2`` above, which already
    handles refreshing via the ``refresh_token`` grant (step 2 there), so
    nothing else needs to change once this has run once per server.
    """
    client_id = credentials.get("client_id", "")
    client_secret = credentials.get("client_secret", "")
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    return await _token_request(
        oauth["token_endpoint"], form, basic=(client_id, client_secret)
    )


async def _dynamically_register_client(
    oauth: dict, server_name: str
) -> dict[str, str]:
    """RFC 7591 dynamic client registration — only used when the authorization
    server advertises a ``registration_endpoint``."""
    registration_endpoint = oauth.get("registration_endpoint")
    if not registration_endpoint:
        raise McpAuthError("No registration_endpoint in OAuth metadata")
    payload = {
        "client_name": server_name or "enterpriseai-mcp-client",
        "grant_types": ["client_credentials", "refresh_token"],
        "response_types": [],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    async with _new_client() as client:
        response = await client.post(registration_endpoint, json=payload)
    if response.status_code not in (200, 201):
        raise McpAuthError(
            f"Dynamic client registration failed ({response.status_code}): "
            f"{response.text[:200]}"
        )
    body = response.json()
    if not body.get("client_id"):
        raise McpAuthError("Registration response missing client_id")
    result = {"client_id": body["client_id"]}
    if body.get("client_secret"):
        result["client_secret"] = body["client_secret"]
    return result


# ── token cache ──────────────────────────────────────────────────────


def _cache_key(server_id: str | None, server_url: str, tenant_id: str | None):
    return (server_id or server_url, tenant_id)


def _cache_get(key) -> str | None:
    entry = _token_cache.get(key)
    if entry and entry["expires_at"] > time.time() + _TOKEN_EXPIRY_MARGIN:
        return entry["access_token"]
    return None


def _cache_put(key, token_response: dict[str, Any]) -> str:
    expires_in = int(token_response.get("expires_in") or 3600)
    _token_cache[key] = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "expires_at": time.time() + expires_in,
    }
    return token_response["access_token"]


def clear_token_cache(server_id: str | None = None) -> None:
    """Drop cached tokens (all, or only one server's)."""
    if server_id is None:
        _token_cache.clear()
    else:
        for key in [k for k in _token_cache if k[0] == server_id]:
            _token_cache.pop(key, None)


# ── main entry point ─────────────────────────────────────────────────


async def resolve_auth(
    db: AsyncSession | None,
    *,
    server_id: str | None,
    server_url: str,
    auth_config: dict,
    credentials: dict[str, str] | None = None,
    tenant_id: str | None = None,
    server_name: str = "",
) -> dict[str, Any]:
    """Resolve ready-to-use auth for an MCP server.

    Returns ``{"headers", "credentials", "auth_type", "token_source"}``:
    ``headers`` go straight into the MCP handshake; ``credentials`` is the
    merged credential map (used for stdio env-var injection).
    """
    stored: dict[str, str] = {}
    if db is not None and server_id:
        try:
            stored = await load_server_credentials(
                db, server_id=server_id, tenant_id=tenant_id
            )
        except McpAuthError:
            logger.warning("Stored credentials for %s are unreadable", server_id)
    # Request-supplied credentials win over stored ones.
    merged: dict[str, str] = {
        **stored,
        **{k: v for k, v in (credentials or {}).items() if v},
    }

    if "GITHUB_TOKEN" in merged and "GITHUB_PERSONAL_ACCESS_TOKEN" not in merged:
        merged["GITHUB_PERSONAL_ACCESS_TOKEN"] = merged["GITHUB_TOKEN"]
    elif "GITHUB_PERSONAL_ACCESS_TOKEN" in merged and "GITHUB_TOKEN" not in merged:
        merged["GITHUB_TOKEN"] = merged["GITHUB_PERSONAL_ACCESS_TOKEN"]

    transport = ((auth_config or {}).get("transport") or "").lower()
    auth_type = ((auth_config or {}).get("auth_type") or "none").lower()

    if auth_type in ("none", "env", "device_pairing") or transport == "stdio":
        return {
            "headers": {},
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials" if merged else None,
        }

    if auth_type == "basic":
        return {
            "headers": _basic_header(merged),
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials",
        }

    if auth_type == "api_key":
        return {
            "headers": _api_key_header(merged),
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials",
        }

    if auth_type == "bearer":
        token = (
            merged.get("access_token")
            or merged.get("token")
            or merged.get("bearer_token")
            or merged.get("jwt")
            or merged.get("api_key")
            or ""
        )
        return {
            "headers": _bearer_header(token) if token else {},
            "credentials": merged,
            "auth_type": auth_type,
            "token_source": "credentials" if token else None,
        }

    if auth_type == "oauth2":
        return await _resolve_oauth2(
            db,
            server_id=server_id,
            server_url=server_url,
            server_name=server_name,
            auth_config=auth_config or {},
            credentials=merged,
            tenant_id=tenant_id,
        )

    # unknown → legacy raw header passthrough
    return {
        "headers": _raw_header_passthrough(merged),
        "credentials": merged,
        "auth_type": auth_type,
        "token_source": "passthrough",
    }


async def _resolve_oauth2(
    db: AsyncSession | None,
    *,
    server_id: str | None,
    server_url: str,
    server_name: str,
    auth_config: dict,
    credentials: dict[str, str],
    tenant_id: str | None,
) -> dict[str, Any]:
    """Acquire an OAuth2 access token natively, trying (in order): cached
    token → refresh_token grant → client_credentials grant → RFC 7591
    dynamic registration → passthrough of a pre-obtained token."""
    key = _cache_key(server_id, server_url, tenant_id)
    oauth = auth_config.get("oauth") or {}
    token_endpoint = oauth.get("token_endpoint") or credentials.get("token_endpoint")
    refresh_token = credentials.get("refresh_token")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")

    def _result(headers: dict[str, str], source: str) -> dict[str, Any]:
        return {
            "headers": headers,
            "credentials": credentials,
            "auth_type": "oauth2",
            "token_source": source,
        }

    # 1. Cached token, still fresh.
    cached = _cache_get(key)
    if cached:
        return _result(_bearer_header(cached), "cache")

    # 2. refresh_token grant (cheapest — also rotates the refresh token).
    if token_endpoint and refresh_token:
        try:
            token_response = await _refresh_token_grant(oauth, credentials, refresh_token)
            _cache_put(key, token_response)
            if token_response.get("refresh_token") and db is not None and server_id:
                await store_server_credentials(
                    db,
                    server_id=server_id,
                    credentials={
                        **credentials,
                        "refresh_token": token_response["refresh_token"],
                    },
                    tenant_id=tenant_id,
                )
            return _result(_bearer_header(token_response["access_token"]), "refresh_token")
        except McpAuthError as exc:
            logger.warning("refresh_token grant failed for %s: %s", server_url, exc)

    # 3. client_credentials grant.
    if token_endpoint and client_id and client_secret:
        try:
            token_response = await _client_credentials_grant(oauth, credentials)
            _cache_put(key, token_response)
            return _result(
                _bearer_header(token_response["access_token"]), "client_credentials"
            )
        except McpAuthError as exc:
            logger.warning("client_credentials grant failed for %s: %s", server_url, exc)

    # 4. RFC 7591 dynamic client registration, then client_credentials.
    if oauth.get("registration_endpoint") and not client_id:
        try:
            registered = await _dynamically_register_client(oauth, server_name)
            credentials = {**credentials, **registered}
            token_response = await _client_credentials_grant(oauth, credentials)
            _cache_put(key, token_response)
            if db is not None and server_id:
                await store_server_credentials(
                    db, server_id=server_id, credentials=credentials, tenant_id=tenant_id
                )
            return _result(
                _bearer_header(token_response["access_token"]), "dynamic_registration"
            )
        except McpAuthError as exc:
            logger.warning("dynamic registration failed for %s: %s", server_url, exc)

    # 5. Passthrough of a pre-obtained token (e.g. a long-lived JWT).
    token = (
        credentials.get("access_token")
        or credentials.get("token")
        or credentials.get("bearer_token")
        or ""
    )
    if token:
        return _result(_bearer_header(token), "passthrough")

    raise McpAuthError(
        "No usable OAuth2 credentials: supply an access_token, a refresh_token, "
        "or client_id + client_secret (client registration endpoint: "
        f"{oauth.get('registration_endpoint') or 'not advertised'})"
    )
