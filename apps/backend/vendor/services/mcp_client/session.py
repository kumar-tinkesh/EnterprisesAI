"""Long-lived MCP sessions for *calling* tools (not just discovering them).

The connect/verify flow (``client.py``) opens a transport, lists tools and
closes. The builder's tool runtime instead needs a session that stays open
across many ``tools/call`` requests. :func:`open_mcp_session` takes the same
config dict ``mcp_service.build_runtime_config`` produces and yields an
initialised :class:`mcp.ClientSession`.

anyio rule: the context manager must be entered and exited by the same task
(the transports run task groups). Callers that pool sessions should keep one
dedicated owner task per session — see ``builder.services.tool_runtime``.
"""
from __future__ import annotations

import asyncio
import shlex
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx2
from mcp import ClientSession

from vendor.services.mcp_client.transport import _DEFAULT_TIMEOUT, _build_auth_headers

_HTTP_TRANSPORTS = {"streamable_http", "http", "streamable-http"}


def runtime_transport(config: dict) -> str:
    transport = (config.get("transport_type") or config.get("transport") or "").lower()
    if transport in _HTTP_TRANSPORTS:
        return "streamable_http"
    if transport in ("sse", "stdio"):
        return transport
    raise ValueError(f"Unsupported transport for tool calls: {transport!r}")


@asynccontextmanager
async def open_mcp_session(
    config: dict,
    *,
    home_dir: Path | None = None,
    connect_timeout: float | None = None,
) -> AsyncIterator[ClientSession]:
    """Open a transport from ``config``, run ``initialize`` and yield the session.

    ``home_dir`` isolates a stdio server's HOME and credential files per user
    (see ``stdio.build_stdio_params``). ``connect_timeout`` bounds the
    initialize handshake only; each tool call sets its own timeout.
    """
    from vendor.services import mcp_client

    transport = runtime_transport(config)
    timeout = float(connect_timeout or config.get("timeout") or _DEFAULT_TIMEOUT)

    if transport == "stdio":
        from vendor.services.mcp_client.stdio import build_stdio_params

        command: str = config.get("command") or ""
        extra_args = list(config.get("args") or [])
        if extra_args:
            command = command.rstrip() + " " + " ".join(shlex.quote(a) for a in extra_args)
        params = await build_stdio_params(
            command,
            config.get("credentials"),
            source_repo_url=config.get("source_repo_url"),
            env_vars=config.get("env_vars"),
            home_dir=home_dir,
        )
        stdio_fn = getattr(mcp_client, "stdio_client")
        async with stdio_fn(params) as (read_stream, write_stream):
            async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                yield session
        return

    endpoint: str = config.get("endpoint") or config.get("server_url") or ""
    if not endpoint:
        raise ValueError("MCP tool runtime: an 'endpoint' is required for HTTP transports")
    headers = config.get("auth_headers")
    if headers is None:
        headers = _build_auth_headers(config.get("credentials"), config.get("auth_type"))

    if transport == "streamable_http":
        streamable_fn = getattr(mcp_client, "streamable_http_client")
        # No overall read timeout on the HTTP client: a tool call may
        # legitimately run for minutes. Per-call timeouts live with the caller.
        # httpx2 (not httpx): what the mcp 2.x streamable client is typed for.
        http_timeout = httpx2.Timeout(connect=timeout, read=None, write=timeout, pool=timeout)
        async with httpx2.AsyncClient(timeout=http_timeout, headers=headers or None) as http:
            async with streamable_fn(endpoint, http_client=http) as (read_stream, write_stream):
                async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=timeout)
                    yield session
        return

    sse_fn = getattr(mcp_client, "sse_client")
    async with sse_fn(endpoint, headers=headers or None, timeout=timeout) as (read_stream, write_stream):
        async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            yield session


__all__ = ["open_mcp_session", "runtime_transport"]
