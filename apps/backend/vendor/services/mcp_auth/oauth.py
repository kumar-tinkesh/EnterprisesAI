"""HTTP Auth headers and OAuth2 protocol flows for mcp_auth."""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from vendor.services.mcp_auth.crypto import McpAuthError
from vendor.services.mcp_auth.storage import (
    _cache_get,
    _cache_key,
    _cache_put,
    store_server_credentials,
)

logger = logging.getLogger("vendor.mcp_auth")

_DEFAULT_TIMEOUT = 15.0

# Header names a caller may pass in ``credentials`` verbatim.
_KNOWN_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token"}


# ── header builders ──


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


# ── OAuth2 token acquisition ──


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

    # Delegate to current package/module _new_client to respect any test monkeypatches
    from vendor.services import mcp_auth

    factory = getattr(mcp_auth, "_new_client", _new_client)
    async with factory() as client:
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
    """RFC 6749 §4.4 client_credentials grant."""
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
    """RFC 6749 §4.1.3 authorization_code grant bootstrap step."""
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
    """RFC 7591 dynamic client registration."""
    registration_endpoint = oauth.get("registration_endpoint")
    if not registration_endpoint:
        raise McpAuthError("No registration_endpoint in OAuth metadata")
    payload = {
        "client_name": server_name or "enterpriseai-mcp-client",
        "grant_types": ["client_credentials", "refresh_token"],
        "response_types": [],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    from vendor.services import mcp_auth

    factory = getattr(mcp_auth, "_new_client", _new_client)
    async with factory() as client:
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


async def _resolve_oauth2(
    db: AsyncSession | None,
    *,
    server_id: str | None,
    server_url: str,
    server_name: str,
    auth_config: dict,
    credentials: dict[str, str],
    tenant_id: str | None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Acquire an OAuth2 access token natively."""
    key = _cache_key(server_id, server_url, tenant_id, user_id)
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

    # 2. refresh_token grant.
    if token_endpoint and refresh_token:
        try:
            from vendor.services import mcp_auth
            refresh_func = getattr(mcp_auth, "_refresh_token_grant", _refresh_token_grant)
            token_response = await refresh_func(oauth, credentials, refresh_token)
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
                    user_id=user_id,
                )
            return _result(_bearer_header(token_response["access_token"]), "refresh_token")
        except McpAuthError as exc:
            logger.warning("refresh_token grant failed for %s: %s", server_url, exc)

    # 3. client_credentials grant.
    if token_endpoint and client_id and client_secret:
        try:
            from vendor.services import mcp_auth
            client_cred_func = getattr(mcp_auth, "_client_credentials_grant", _client_credentials_grant)
            token_response = await client_cred_func(oauth, credentials)
            _cache_put(key, token_response)
            return _result(
                _bearer_header(token_response["access_token"]), "client_credentials"
            )
        except McpAuthError as exc:
            logger.warning("client_credentials grant failed for %s: %s", server_url, exc)

    # 4. RFC 7591 dynamic client registration.
    if oauth.get("registration_endpoint") and not client_id:
        try:
            from vendor.services import mcp_auth
            dyn_func = getattr(mcp_auth, "_dynamically_register_client", _dynamically_register_client)
            client_cred_func = getattr(mcp_auth, "_client_credentials_grant", _client_credentials_grant)
            registered = await dyn_func(oauth, server_name)
            credentials = {**credentials, **registered}
            token_response = await client_cred_func(oauth, credentials)
            _cache_put(key, token_response)
            if db is not None and server_id:
                await store_server_credentials(
                    db,
                    server_id=server_id,
                    credentials=credentials,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            return _result(
                _bearer_header(token_response["access_token"]), "dynamic_registration"
            )
        except McpAuthError as exc:
            logger.warning("dynamic registration failed for %s: %s", server_url, exc)

    # 5. Passthrough of a pre-obtained token.
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
