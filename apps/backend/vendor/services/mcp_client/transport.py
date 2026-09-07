"""Network transports (streamable_http, sse), auth headers mapping, and MCP handshakes for mcp_client."""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("vendor.mcp_client")

_DEFAULT_TIMEOUT = 30.0
_KNOWN_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token"}


def _detect_transport(server_url: str) -> str:
    """Auto-detect transport from the server URL/command string."""
    if not server_url:
        return "stdio"
    url_lower = server_url.lower().strip()
    if "github.com" in url_lower:
        return "stdio"
    if url_lower.startswith("http://") or url_lower.startswith("https://"):
        return "streamable_http"
    return "stdio"


def _build_auth_headers(
    credentials: dict[str, str] | None,
    auth_type: str | None = None,
) -> dict[str, str]:
    """Map a credentials dict + detected auth type into HTTP auth headers."""
    if not credentials:
        return {}

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


async def _session_details(read_stream: Any, write_stream: Any) -> dict:
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
    from vendor.services import mcp_client

    session_details_fn = getattr(mcp_client, "_session_details", _session_details)
    if transport == "streamable_http":
        streamable_fn = getattr(mcp_client, "streamable_http_client", streamable_http_client)
        async with httpx.AsyncClient(timeout=timeout, headers=headers or None) as http:
            async with streamable_fn(server_url, http_client=http) as (
                read_stream,
                write_stream,
            ):
                return await session_details_fn(read_stream, write_stream)
    if transport == "sse":
        sse_fn = getattr(mcp_client, "sse_client", sse_client)
        async with sse_fn(server_url, headers=headers or None, timeout=timeout) as (
            read_stream,
            write_stream,
        ):
            return await session_details_fn(read_stream, write_stream)
    raise ValueError(f"Unsupported transport: {transport}")
