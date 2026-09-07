"""MCPClient class and connect_mcp_server wrapper function for mcp_client."""
from __future__ import annotations
import logging
import shlex

from vendor.services.mcp_client.stdio import _connect_stdio
from vendor.services.mcp_client.transport import (
    _DEFAULT_TIMEOUT,
    _build_auth_headers,
    _detect_transport,
    _handshake,
)

logger = logging.getLogger("vendor.mcp_client")


class MCPClient:
    """Generic MCP client — dispatches to the correct adapter based on transport."""

    async def connect(self, config: dict) -> dict:
        """Connect using a normalized config dict."""
        transport = config.get("transport_type") or config.get("transport")
        if transport == "stdio":
            return await self._stdio_adapter(config)
        elif transport == "streamable_http":
            return await self._streamable_http_adapter(config)
        elif transport == "sse":
            return await self._sse_adapter(config)
        else:
            raise ValueError(
                f"Unsupported transport: {transport!r}. "
                "Expected 'stdio', 'streamable_http', or 'sse'."
            )

    async def _stdio_adapter(self, config: dict) -> dict:
        """STDIO adapter — spawns a local process and runs the MCP handshake."""
        command: str = config.get("command") or ""
        extra_args: list[str] = list(config.get("args") or [])
        if extra_args:
            command = command.rstrip() + " " + " ".join(shlex.quote(a) for a in extra_args)

        credentials: dict[str, str] | None = config.get("credentials")
        source_repo_url: str | None = config.get("source_repo_url")
        env_vars: dict[str, str] | None = config.get("env_vars")
        working_directory: str | None = config.get("working_directory")

        result = await _connect_stdio(
            command,
            credentials,
            source_repo_url=source_repo_url,
            env_vars=env_vars,
        )

        if working_directory:
            result.setdefault("working_directory", working_directory)

        return result

    async def _streamable_http_adapter(self, config: dict) -> dict:
        """Streamable HTTP adapter — POST-based MCP over HTTP(S)."""
        endpoint: str = config.get("endpoint") or config.get("server_url") or ""
        if not endpoint:
            raise ValueError("MCPClient._streamable_http_adapter: 'endpoint' is required")

        auth_type: str | None = config.get("auth_type")
        credentials: dict[str, str] | None = config.get("credentials")
        auth_headers: dict[str, str] | None = config.get("auth_headers")
        timeout: float = float(config.get("timeout") or _DEFAULT_TIMEOUT)

        headers = (
            auth_headers
            if auth_headers is not None
            else _build_auth_headers(credentials, auth_type)
        )

        details = await _handshake("streamable_http", endpoint, headers, timeout)
        logger.info(
            "streamable_http connected to %s — discovered %d tool(s)",
            endpoint,
            len(details["tools"]),
        )
        return {
            "transport": "streamable_http",
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }

    async def _sse_adapter(self, config: dict) -> dict:
        """SSE adapter — GET-based Server-Sent Events transport."""
        endpoint: str = config.get("endpoint") or config.get("server_url") or ""
        if not endpoint:
            raise ValueError("MCPClient._sse_adapter: 'endpoint' is required")

        auth_type: str | None = config.get("auth_type")
        credentials: dict[str, str] | None = config.get("credentials")
        auth_headers: dict[str, str] | None = config.get("auth_headers")
        timeout: float = float(config.get("timeout") or _DEFAULT_TIMEOUT)

        headers = (
            auth_headers
            if auth_headers is not None
            else _build_auth_headers(credentials, auth_type)
        )

        details = await _handshake("sse", endpoint, headers, timeout)
        logger.info(
            "sse connected to %s — discovered %d tool(s)",
            endpoint,
            len(details["tools"]),
        )
        return {
            "transport": "sse",
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }


async def connect_mcp_server(
    server_url: str,
    credentials: dict[str, str] | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    auth_headers: dict[str, str] | None = None,
    source_repo_url: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Connect to an MCP server and return {transport, bound_tools, tools, ...}."""
    target = server_url.strip()
    transport = transport or _detect_transport(target)

    if transport == "stdio":
        return await _connect_stdio(
            target, credentials, source_repo_url=source_repo_url, env_vars=env_vars
        )

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
