"""MCP client helper package — auto-detects transport and discovers tools.

Consolidates stdio execution, network transport handshakes, and client dispatching
into a modular package layout while preserving 100% backward compatibility.
"""
from __future__ import annotations

import os
import shutil

from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from vendor.services.mcp_client.client import MCPClient, connect_mcp_server
from vendor.services.mcp_client.stdio import (
    _PACKAGE_RUNNER_COMMANDS,
    _REPO_BUILD_TIMEOUT,
    _REPO_CLONE_TIMEOUT,
    _best_python_entry,
    _connect_stdio,
    _fetch_repo_tarball,
    _pick_local_entry,
    _prepare_local_repo_stdio,
    _python_console_entry_code,
    _python_module_base,
    _sanitize_stdio_env,
)
from vendor.services.mcp_client.transport import (
    _DEFAULT_TIMEOUT,
    _KNOWN_AUTH_HEADERS,
    _build_auth_headers,
    _detect_transport,
    _handshake,
    _normalize_tool,
    _session_details,
)

__all__ = [
    "MCPClient",
    "connect_mcp_server",
    "stdio_client",
    "sse_client",
    "streamable_http_client",
    "_DEFAULT_TIMEOUT",
    "_KNOWN_AUTH_HEADERS",
    "_PACKAGE_RUNNER_COMMANDS",
    "_REPO_CLONE_TIMEOUT",
    "_REPO_BUILD_TIMEOUT",
    "_detect_transport",
    "_build_auth_headers",
    "_normalize_tool",
    "_session_details",
    "_handshake",
    "_prepare_local_repo_stdio",
    "_connect_stdio",
    "_sanitize_stdio_env",
    "_pick_local_entry",
    "_best_python_entry",
    "_python_console_entry_code",
    "_python_module_base",
    "_fetch_repo_tarball",
    "shutil",
    "os",
]
