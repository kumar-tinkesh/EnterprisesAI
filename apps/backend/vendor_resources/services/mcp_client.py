"""MCP client helper — auto-detects transport and discovers tools.

Connects to an MCP server over the official ``mcp`` SDK, performing the MCP
handshake (``initialize``) and ``tools/list`` discovery. Supported transports:

- ``streamable_http`` — POST-based streamable HTTP (modern MCP servers)
- ``sse``             — GET-based Server-Sent Events (legacy MCP servers)
- ``stdio``           — a local command string (``npx -y some-mcp-server …``)

Credentials are injected per transport, mirroring the MRKTPLCE ``mcp_runtime``
design: auth *headers* for network transports, environment variables for
spawned stdio processes.
"""
from __future__ import annotations

import base64
import logging
import os
import shlex
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("vendor_resources.mcp_client")

_DEFAULT_TIMEOUT = 30.0

# Header names a caller may pass in ``credentials`` verbatim (backward-compat:
# older clients sent a raw header map). Anything else is mapped via auth_type.
_KNOWN_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token"}


def _detect_transport(server_url: str) -> str:
    """Auto-detect transport from the server URL/command string."""
    if server_url.startswith("http://") or server_url.startswith("https://"):
        return "streamable_http"
    return "stdio"


def _build_auth_headers(
    credentials: dict[str, str] | None,
    auth_type: str | None = None,
) -> dict[str, str]:
    """Map a credentials dict + detected auth type into HTTP auth headers.

    Mapping rules (``auth_type`` comes from ``services.mcp_detect``):
      - ``bearer``/``oauth2`` → ``Authorization: Bearer <token>``
      - ``api_key``           → ``X-API-Key: <key>`` (or ``Authorization`` if
        the caller supplied a header-named key directly)
      - ``basic``             → ``Authorization: Basic base64(user:pass)``
      - ``none``/unknown      → raw header passthrough (legacy behaviour)
    """
    if not credentials:
        return {}

    # Raw header passthrough takes precedence for backward compatibility:
    # previously the whole credentials dict was used as headers.
    direct = {
        k: v
        for k, v in credentials.items()
        if k.lower() in _KNOWN_AUTH_HEADERS or ":" in k
    }
    if direct and auth_type in (None, "", "none", "unknown"):
        return direct

    auth_type = (auth_type or "").lower()
    headers: dict[str, str] = {}

    if auth_type == "basic":
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    elif auth_type in ("bearer", "oauth2"):
        token = (
            credentials.get("access_token")
            or credentials.get("token")
            or credentials.get("bearer_token")
            or credentials.get("api_key")
            or ""
        )
        if token:
            if token.startswith("Bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        api_key = (
            credentials.get("api_key")
            or credentials.get("api-key")
            or credentials.get("x-api-key")
            or ""
        )
        if api_key:
            header_name = credentials.get("header_name") or "X-API-Key"
            if header_name.lower() == "authorization":
                prefix = credentials.get("header_prefix", "Bearer ")
                headers["Authorization"] = f"{prefix}{api_key}"
            else:
                headers[header_name] = api_key
    elif direct:
        return direct

    # Merge any explicit raw headers on top.
    headers.update(direct)
    return headers


def _normalize_tool(tool: Any) -> dict[str, Any]:
    """Normalize an MCP tool model into a plain dict with full metadata."""
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "input_schema": getattr(tool, "input_schema", None)
        or {"type": "object", "properties": {}},
    }


async def _session_details(read_stream, write_stream) -> dict:
    """Run initialize + tools/list on an established transport pair."""
    async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
        init = await session.initialize()
        result = await session.list_tools()
        tools = [_normalize_tool(t) for t in (result.tools or [])]
        server_info = getattr(init, "server_info", None)
        return {
            "server_info": {
                "name": getattr(server_info, "name", None),
                "version": getattr(server_info, "version", None),
            }
            if server_info
            else None,
            "protocol_version": getattr(init, "protocol_version", None),
            "tools": tools,
        }


async def _handshake(
    transport: str,
    server_url: str,
    headers: dict[str, str] | None,
    timeout: float,
) -> dict:
    """Perform the MCP handshake over an http(s) transport."""
    if transport == "streamable_http":
        async with httpx.AsyncClient(timeout=timeout, headers=headers or None) as http:
            async with streamable_http_client(server_url, http_client=http) as (
                read_stream,
                write_stream,
            ):
                return await _session_details(read_stream, write_stream)
    if transport == "sse":
        async with sse_client(server_url, headers=headers or None, timeout=timeout) as (
            read_stream,
            write_stream,
        ):
            return await _session_details(read_stream, write_stream)
    raise ValueError(f"Unsupported transport: {transport}")


async def connect_mcp_server(
    server_url: str,
    credentials: dict[str, str] | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    auth_headers: dict[str, str] | None = None,
) -> dict:
    """Connect to an MCP server and return {transport, bound_tools, tools, ...}.

    Transport is auto-detected from the URL scheme when not given: http(s)
    URLs try streamable HTTP first, then fall back to SSE; anything else is
    treated as a stdio command. Auth resolution is native via
    ``services.mcp_auth.resolve_auth`` — pass its ``headers`` result as
    ``auth_headers``; if omitted, credentials are mapped into auth headers
    directly (legacy path). Credentials are also injected as environment
    variables (stdio).
    """
    target = server_url.strip()
    transport = transport or _detect_transport(target)

    if transport == "stdio":
        return await _connect_stdio(target, credentials)

    headers = (
        auth_headers
        if auth_headers is not None
        else _build_auth_headers(credentials, auth_type)
    )
    attempts: list[str] = ["sse"] if transport == "sse" else ["streamable_http", "sse"]
    last_error: Exception | None = None
    for candidate in attempts:
        try:
            details = await _handshake(candidate, target, headers, timeout)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.debug("MCP handshake via %s failed for %s: %s", candidate, target, exc)
            continue
        logger.info(
            "%s connected to %s — discovered %d tool(s)",
            candidate,
            target,
            len(details["tools"]),
        )
        return {
            "transport": candidate,
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }
    raise ConnectionError(f"Failed to connect via {attempts}: {last_error}")


async def _connect_stdio(command: str, credentials: dict[str, str] | None) -> dict:
    """Spawn a stdio MCP server process, inject credentials as env vars and
    substitute ``{field}`` placeholders in the command with credential values
    (e.g. ``npx -y x/y-mcp --token {api_key}``)."""
    env = {**os.environ}
    parts = shlex.split(command)
    if credentials:
        env.update({k.upper(): v for k, v in credentials.items()})
        parts = [
            next(
                (v for k, v in credentials.items() if part == "{" + k + "}"),
                part,
            )
            for part in parts
        ]
    params = StdioServerParameters(command=parts[0], args=parts[1:], env=env)
    async with stdio_client(params) as (read_stream, write_stream):
        details = await _session_details(read_stream, write_stream)
    logger.info("stdio connected to %s — discovered %d tool(s)", command, len(details["tools"]))
    return {
        "transport": "stdio",
        "bound_tools": [t["name"] for t in details["tools"]],
        "tools": details["tools"],
        "server_info": details["server_info"],
        "protocol_version": details["protocol_version"],
        "auth_type": "env" if credentials else "none",
    }

