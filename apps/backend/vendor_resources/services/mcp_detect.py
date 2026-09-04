"""Native MCP server detection — probe any MCP URL/command and determine which
type of credential it wants *before* connecting.

Detection is **standards-driven and contains zero provider-specific
hardcoding**: no vendor, hosted product, or hostname is referenced anywhere
in this module. Every classification comes from what the server itself
advertises.

Detection pipeline for an ``http(s)://`` URL:
  1. Probe candidate endpoints (the URL itself, then ``<url>/mcp`` and
     ``<url>/sse``) with an unauthenticated MCP ``initialize`` request.
  2. A ``200`` on a POST probe means the endpoint is open over streamable HTTP
     (``auth_type == "none"``, ``transport_confidence == 0.99``).
  3. A ``200`` on a GET probe with ``text/event-stream`` means an open SSE
     endpoint (``transport_confidence == 0.95``).
  4. A ``401``/``403`` on a POST means auth is required over streamable HTTP
     (``transport_confidence == 0.80``). The ``WWW-Authenticate`` challenge
     is parsed per RFC 6750:
       - ``Basic``            → ``basic``
       - ``Bearer``           → ``bearer`` (upgraded to ``oauth2`` when OAuth
         metadata is discovered, since a Bearer challenge alone may also be a
         static API token or JWT)
       - any custom scheme    → ``api_key``
  5. In parallel, OAuth metadata is discovered per the MCP authorization spec:
       - ``resource_metadata="…"`` parameter of the Bearer challenge
         (RFC 9728 §5.1), or ``/.well-known/oauth-protected-resource``
       - → ``authorization_servers[]`` → RFC 8414 / OIDC discovery
         (``/.well-known/oauth-authorization-server``,
         ``/.well-known/openid-configuration``)
     A discovered ``token_endpoint`` classifies the server as ``oauth2`` and
     is persisted in the result (``oauth`` block) so the runtime auth engine
     can acquire tokens natively without re-probing.
  6. If nothing answers, the server is reported as unreachable/unknown with
     the probe evidence in ``hints`` — never guessed from URL patterns.

For a non-URL input the value is treated as a ``stdio`` command; credential
requirements cannot be probed for stdio, so the caller is told credentials
(if any) are supplied as env vars (``auth_type == "env"``).

Every result now includes:
  - ``transport_confidence`` (float 0.0–1.0) — how certain the transport
    classification is. Values:
      0.99  POST /mcp returned 200 (definitive streamable HTTP)
      0.95  GET /sse returned 200 + text/event-stream (definitive SSE)
      0.80  POST returned 401/403 (challenge implies streamable HTTP)
      0.70  OAuth well-known metadata discovered without a live probe
      0.50  Only heuristic / fallback evidence
      0.10  Unreachable — transport is a guess
      1.00  stdio command (no network ambiguity)
  - ``transport_evidence`` (list of ``{source, reason}`` dicts) — ordered
    list of signals that drove the classification, most authoritative first.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("vendor_resources.mcp_detect")

_PROBE_TIMEOUT = 10.0

# A minimal but valid MCP initialize request, used to classify the endpoint.
_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "enterpriseai-probe", "version": "1.0.0"},
    },
}

# RFC 9728 protected-resource metadata location (relative to the resource).
_PROTECTED_RESOURCE_WELLKNOWN = "/.well-known/oauth-protected-resource"
# RFC 8414 / OIDC authorization-server metadata locations (relative to issuer).
_AUTH_SERVER_WELLKNOWN_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
)

# Mapping from legacy string confidence values to float scores.
_CONFIDENCE_FLOAT: dict[str, float] = {
    "command":    1.00,  # stdio — no network ambiguity
    "open":       0.99,  # 200 on POST → streamable_http (updated inline for SSE)
    "challenge":  0.80,  # 401/403 on POST → streamable_http, auth required
    "well-known": 0.70,  # OAuth metadata discovered without a live probe
    "hint":       0.50,  # heuristic / fallback
    "none":       0.10,  # unreachable
}


class McpDetectError(Exception):
    """Raised when detection cannot be performed at all (invalid input)."""


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


def _credential_fields(auth_type: str) -> list[dict]:
    """The credential form fields a UI should render for the given auth type."""
    if auth_type in ("bearer", "oauth2"):
        fields = [
            {
                "name": "access_token",
                "label": "Access token" if auth_type == "oauth2" else "Bearer token",
                "type": "password",
                "placeholder": "eyJhbGciOi…",
                "secret": True,
                "required": True,
            }
        ]
        if auth_type == "oauth2":
            fields += [
                {"name": "client_id", "label": "Client ID", "type": "text", "placeholder": "", "secret": False, "required": False},
                {"name": "client_secret", "label": "Client secret", "type": "password", "placeholder": "", "secret": True, "required": False},
            ]
        return fields
    if auth_type == "api_key":
        return [
            {"name": "api_key", "label": "API key", "type": "password", "placeholder": "sk-…", "secret": True, "required": True}
        ]
    if auth_type == "basic":
        return [
            {"name": "username", "label": "Username", "type": "text", "placeholder": "user@example.com", "secret": False, "required": True},
            {"name": "password", "label": "Password / API token", "type": "password", "placeholder": "", "secret": True, "required": True},
        ]
    return []


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


async def detect_mcp_server(
    server_url: str,
    *,
    credentials: dict[str, str] | None = None,
    timeout: float = _PROBE_TIMEOUT,
) -> dict:
    """Probe ``server_url`` and report transport + required credential type.

    Returns a dict shaped for the ``POST /mcp/detect`` endpoint:
    ``{ok, server_url, transport, endpoint, reachable, auth_required,
    auth_type, confidence, credential_fields, hints, oauth_scopes, error,
    transport_confidence, transport_evidence}``.

    New fields:
      - ``transport_confidence`` — float 0.0–1.0 certainty of transport type.
      - ``transport_evidence``   — ordered list of ``{source, reason}`` dicts
        explaining what signal(s) drove the classification.
    """
    target = server_url.strip()
    if not target:
        raise McpDetectError("server_url must not be empty")

    # ── stdio command ────────────────────────────────────────────────────
    if not (target.startswith("http://") or target.startswith("https://")):
        return {
            "ok": True,
            "server_url": target,
            "transport": "stdio",
            "endpoint": target,
            "reachable": None,  # cannot probe without spawning the process
            "auth_required": None,
            "auth_type": "env",
            "confidence": "command",
            "credential_fields": [],
            "hints": [
                "stdio command detected — credentials, if the server needs "
                "any, are supplied as environment variables or {field} "
                "substitutions in the command"
            ],
            "oauth_scopes": [],
            "error": None,
            "transport_confidence": 1.0,
            "transport_evidence": [
                {
                    "source": "input_format",
                    "reason": (
                        "Input does not start with http:// or https://, "
                        "therefore treated as a stdio command."
                    ),
                }
            ],
        }

    hints: list[str] = []
    last_status: int | None = None
    working_endpoint: str | None = None

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for candidate in _candidate_urls(target):
            try:
                response, probe_method = await _probe_endpoint(client, candidate)
            except httpx.HTTPError as exc:
                logger.debug("probe %s failed: %s", candidate, exc)
                continue
            last_status = response.status_code
            working_endpoint = candidate

            if response.status_code in (401, 403):
                # POST returned an auth challenge → transport is streamable HTTP.
                auth_type, challenge_hints = _classify_challenge(
                    response.headers.get("www-authenticate")
                )
                hints.extend(challenge_hints)
                evidence: list[dict] = [
                    {
                        "source": f"http_probe POST {candidate}",
                        "reason": (
                            f"POST /mcp returned HTTP {response.status_code} "
                            "(auth challenge) — transport is streamable_http, "
                            "authentication is required."
                        ),
                    }
                ]
                www_auth = response.headers.get("www-authenticate")
                if www_auth:
                    evidence.append(
                        {
                            "source": "www-authenticate_header",
                            "reason": f"WWW-Authenticate: {www_auth}",
                        }
                    )
                # Standards-driven OAuth discovery (RFC 9728 → RFC 8414).
                # Upgrades a Bearer challenge to oauth2 and carries the
                # token/registration endpoints the auth engine needs.
                oauth = await _discover_oauth_metadata(
                    client,
                    target,
                    www_authenticate=response.headers.get("www-authenticate"),
                    hints=hints,
                )
                if oauth and auth_type in ("bearer", "unknown"):
                    auth_type = "oauth2"
                    evidence.append(
                        {
                            "source": "oauth_well-known_discovery",
                            "reason": (
                                f"RFC 9728/8414 OAuth metadata discovered; "
                                f"token_endpoint={oauth.get('token_endpoint')} — "
                                "upgraded auth_type to oauth2."
                            ),
                        }
                    )
                legacy_confidence = "challenge" if auth_type != "unknown" else "hint"
                return _result(
                    target, candidate, "streamable_http",
                    reachable=True, auth_required=True,
                    auth_type=auth_type,
                    confidence=legacy_confidence,
                    hints=hints,
                    oauth=oauth,
                    transport_confidence=0.80,
                    transport_evidence=evidence,
                )

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "").lower()
                is_sse = "text/event-stream" in content_type

                if probe_method == "GET" and is_sse:
                    # Definitive SSE: GET probe returned event-stream.
                    transport = "sse"
                    t_confidence = 0.95
                    evidence = [
                        {
                            "source": f"http_probe GET {candidate}",
                            "reason": (
                                f"GET {candidate} returned HTTP 200 with "
                                f"Content-Type: {content_type} — "
                                "confirmed SSE (Server-Sent Events) transport."
                            ),
                        }
                    ]
                elif probe_method == "POST" and not is_sse:
                    # Definitive streamable HTTP: POST returned JSON/200.
                    transport = "streamable_http"
                    t_confidence = 0.99
                    evidence = [
                        {
                            "source": f"http_probe POST {candidate}",
                            "reason": (
                                f"POST {candidate} returned HTTP 200 with "
                                f"Content-Type: {content_type} — "
                                "confirmed streamable_http transport."
                            ),
                        }
                    ]
                elif probe_method == "POST" and is_sse:
                    # POST returned SSE stream — unusual but valid; treat as SSE.
                    transport = "sse"
                    t_confidence = 0.90
                    evidence = [
                        {
                            "source": f"http_probe POST {candidate}",
                            "reason": (
                                f"POST {candidate} returned HTTP 200 with "
                                f"Content-Type: {content_type} (event-stream) — "
                                "classified as SSE transport (POST+SSE response)."
                            ),
                        }
                    ]
                else:
                    # GET probe returned 200 without event-stream header —
                    # ambiguous; assume streamable_http with moderate confidence.
                    transport = "streamable_http"
                    t_confidence = 0.70
                    evidence = [
                        {
                            "source": f"http_probe GET {candidate}",
                            "reason": (
                                f"GET {candidate} returned HTTP 200 with "
                                f"Content-Type: {content_type} (no event-stream) — "
                                "assumed streamable_http (ambiguous)."
                            ),
                        }
                    ]

                return _result(
                    target, candidate, transport,
                    reachable=True, auth_required=False, auth_type="none",
                    confidence="open",
                    hints=["Endpoint answered an unauthenticated MCP initialize — no credentials required"],
                    transport_confidence=t_confidence,
                    transport_evidence=evidence,
                )
            # 404 etc. on this candidate → try the next conventional path.

        # No candidate answered 200/401/403 → try OAuth well-known metadata
        # directly (server behind a proxy that swallows the challenge, etc.).
        oauth = await _discover_oauth_metadata(client, target, hints=hints)
        if oauth:
            evidence = [
                {
                    "source": "oauth_well-known_discovery",
                    "reason": (
                        "No live HTTP probe succeeded, but RFC 9728/8414 OAuth "
                        "metadata was discovered at the well-known endpoint — "
                        "transport inferred as streamable_http."
                    ),
                }
            ]
            return _result(
                target, target, "streamable_http", reachable=False,
                auth_required=True, auth_type="oauth2",
                confidence="well-known",
                hints=hints,
                oauth=oauth,
                transport_confidence=0.70,
                transport_evidence=evidence,
            )

    # Completely unreachable.
    evidence = [
        {
            "source": "http_probe_exhausted",
            "reason": (
                f"All candidate endpoints probed — none returned 200/401/403 "
                f"(last HTTP status: {last_status}). Transport cannot be "
                "determined; defaulting to streamable_http as the modern standard."
            ),
        }
    ]
    return _result(
        target, working_endpoint or target, "streamable_http",
        reachable=False, auth_required=None, auth_type="unknown",
        confidence="none",
        hints=hints + [
            f"No MCP endpoint answered (last HTTP status: {last_status}). "
            "Is the server running and the URL correct?"
        ],
        error=f"unreachable (last status {last_status})",
        transport_confidence=0.10,
        transport_evidence=evidence,
    )


def _result(
    server_url: str,
    endpoint: str | None,
    transport: str | None,
    *,
    reachable: bool | None,
    auth_required: bool | None,
    auth_type: str,
    confidence: str,
    hints: list[str],
    oauth_scopes: list[str] | None = None,
    oauth: dict | None = None,
    error: str | None = None,
    transport_confidence: float | None = None,
    transport_evidence: list[dict] | None = None,
) -> dict:
    """Build the uniform detection response, including the credential fields
    the UI should render for the detected auth type and the discovered OAuth
    metadata (``oauth``) the runtime auth engine consumes.

    Now also includes:
      - ``transport_confidence`` — float 0.0–1.0 certainty of transport type.
        Derived from the ``confidence`` string when not supplied explicitly.
      - ``transport_evidence``   — ordered list of ``{source, reason}`` dicts
        explaining what signal(s) drove the classification.
    """
    oauth = oauth or {}
    # Derive float confidence from the legacy string when not explicitly set.
    if transport_confidence is None:
        transport_confidence = _CONFIDENCE_FLOAT.get(confidence, 0.50)

    return {
        "ok": error is None,
        "server_url": server_url,
        "transport": transport or "unknown",
        "endpoint": endpoint or server_url,
        "reachable": reachable,
        "auth_required": auth_required,
        "auth_type": auth_type,
        "confidence": confidence,
        "credential_fields": _credential_fields(auth_type)
        if auth_type not in ("none", "env", "unknown")
        else [],
        "hints": hints,
        "oauth_scopes": oauth_scopes or oauth.get("scopes_supported") or [],
        "oauth": oauth,
        "error": error,
        # New fields — always present.
        "transport_confidence": transport_confidence,
        "transport_evidence": transport_evidence or [],
    }
