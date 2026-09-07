"""Main detection pipeline and uniform result builder for mcp_detect."""
from __future__ import annotations

import logging

import httpx

from vendor.services.mcp_detect.probes import (
    _candidate_urls,
    _classify_challenge,
    _discover_oauth_metadata,
    _probe_endpoint,
)
from vendor.services.mcp_detect.types import (
    _CONFIDENCE_FLOAT,
    _PROBE_TIMEOUT,
    McpDetectError,
    _credential_fields,
)

logger = logging.getLogger("vendor.mcp_detect")


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
    """Build the uniform detection response, including credential fields and OAuth metadata."""
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
        "transport_confidence": transport_confidence,
        "transport_evidence": transport_evidence or [],
    }


async def detect_mcp_server(
    server_url: str,
    *,
    credentials: dict[str, str] | None = None,
    timeout: float = _PROBE_TIMEOUT,
) -> dict:
    """Probe ``server_url`` and report transport + required credential type."""
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

    from vendor.services import mcp_detect
    client_cls = getattr(mcp_detect.httpx, "AsyncClient", httpx.AsyncClient)

    async with client_cls(timeout=timeout, follow_redirects=False) as client:
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
                    # GET probe returned 200 without event-stream header — assume streamable_http.
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

        # No candidate answered 200/401/403 → try OAuth well-known metadata directly.
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
