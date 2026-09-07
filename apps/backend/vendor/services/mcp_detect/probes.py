"""HTTP probing & RFC 9728 / RFC 8414 OAuth metadata discovery for mcp_detect."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx

from vendor.services.mcp_detect.types import (
    _AUTH_SERVER_WELLKNOWN_PATHS,
    _INITIALIZE_BODY,
    _PROTECTED_RESOURCE_WELLKNOWN,
)

logger = logging.getLogger("vendor.mcp_detect")


def _candidate_urls(server_url: str) -> list[str]:
    """Probe candidates: the URL as-given, then conventional MCP endpoints."""
    base = server_url.rstrip("/")
    candidates = [base]
    for suffix in ("/mcp", "/sse"):
        if not base.endswith(suffix):
            candidates.append(base + suffix)
    return candidates


def _classify_challenge(www_authenticate: str | None) -> tuple[str, list[str]]:
    """Map a ``WWW-Authenticate`` challenge to (auth_type, hints)."""
    if not www_authenticate:
        return "unknown", []
    challenge = www_authenticate.strip()
    scheme = challenge.split(" ", 1)[0].lower()
    hints = [f"Server auth challenge: {challenge}"]
    if scheme == "bearer":
        # A Bearer challenge alone does not prove OAuth2 — it may be a static
        # API token or JWT. detect_mcp_server upgrades this to "oauth2" only
        # when RFC 8414/9728 OAuth metadata is actually discovered.
        return "bearer", hints
    if scheme == "basic":
        return "basic", hints
    # Custom scheme (ApiKey, Token, x-api-key, …) → treat as API key.
    return "api_key", hints


async def _probe_endpoint(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, str]:
    """Send one unauthenticated MCP ``initialize`` probe to ``url``.

    Returns ``(response, probe_method)`` where ``probe_method`` is either
    ``"POST"`` (streamable-HTTP probe) or ``"GET"`` (SSE probe).

    A streamable-HTTP MCP endpoint answers a POST; an SSE endpoint answers a
    GET with ``text/event-stream``. Everything else surfaces the last status.
    """
    response = await client.post(
        url,
        json=_INITIALIZE_BODY,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    # 405/406/404 → not a POST endpoint; try the SSE (GET) probe.
    if response.status_code in (404, 405, 406):
        get_response = await client.get(
            url,
            headers={"Accept": "text/event-stream"},
        )
        return get_response, "GET"
    return response, "POST"


def _resource_metadata_url(www_authenticate: str | None) -> str | None:
    """Extract ``resource_metadata="https://…"`` from a challenge (RFC 9728 §5.1)."""
    if not www_authenticate:
        return None
    match = re.search(
        r'resource_metadata\s*=\s*"([^"]+)"', www_authenticate, re.IGNORECASE
    )
    return match.group(1) if match else None


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    """GET a URL and return the parsed JSON object, or None on any failure."""
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.debug("metadata fetch %s failed: %s", url, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — malformed JSON is just "no metadata"
        return None
    return body if isinstance(body, dict) else None


async def _authorization_server_metadata(
    client: httpx.AsyncClient, issuer_base: str
) -> dict | None:
    """Fetch RFC 8414 / OIDC authorization-server metadata for an issuer."""
    base = issuer_base.rstrip("/")
    for path in _AUTH_SERVER_WELLKNOWN_PATHS:
        body = await _fetch_json(client, base + path)
        if body and body.get("token_endpoint"):
            return body
    return None


async def _discover_oauth_metadata(
    client: httpx.AsyncClient,
    target: str,
    *,
    www_authenticate: str | None = None,
    hints: list[str] | None = None,
) -> dict | None:
    """Discover OAuth2 metadata per RFC 9728 + RFC 8414 + the MCP auth spec.

    Discovery chain (no provider-specific logic anywhere):
      1. ``resource_metadata="…"`` parameter of the WWW-Authenticate challenge.
      2. ``/.well-known/oauth-protected-resource`` on the resource base URL.
      3. ``authorization_servers[]`` from the protected-resource document →
         RFC 8414 / OIDC discovery on each issuer.
      4. Fallback: treat the resource base URL itself as an authorization
         server and try AS discovery directly.

    Returns a normalized dict ``{authorization_server, token_endpoint,
    registration_endpoint, scopes_supported, grant_types_supported}`` or None.
    """
    hints = hints if hints is not None else []
    candidates: list[str] = []
    rm_url = _resource_metadata_url(www_authenticate)
    if rm_url:
        candidates.append(rm_url)
    candidates.append(_base_url(target).rstrip("/") + _PROTECTED_RESOURCE_WELLKNOWN)

    as_meta: dict | None = None
    for candidate in candidates:
        resource_doc = await _fetch_json(client, candidate)
        if not resource_doc:
            continue
        scopes = resource_doc.get("scopes_supported") or []
        if scopes:
            hints.append(f"OAuth scopes advertised: {', '.join(map(str, scopes))}")
        for issuer in resource_doc.get("authorization_servers") or []:
            as_meta = await _authorization_server_metadata(client, str(issuer))
            if as_meta:
                break
        if as_meta is None and resource_doc.get("token_endpoint"):
            # The protected-resource document doubles as AS metadata.
            as_meta = resource_doc
        if as_meta:
            break

    if as_meta is None:
        # Last resort: the resource base may itself be the authorization server.
        as_meta = await _authorization_server_metadata(client, _base_url(target))
    if not as_meta or not as_meta.get("token_endpoint"):
        return None

    hints.append(f"OAuth2 token endpoint discovered: {as_meta['token_endpoint']}")
    return {
        "authorization_server": as_meta.get("issuer"),
        "token_endpoint": as_meta["token_endpoint"],
        "registration_endpoint": as_meta.get("registration_endpoint"),
        "scopes_supported": as_meta.get("scopes_supported") or [],
        "grant_types_supported": as_meta.get("grant_types_supported")
        or ["authorization_code", "refresh_token"],
    }


def _base_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
