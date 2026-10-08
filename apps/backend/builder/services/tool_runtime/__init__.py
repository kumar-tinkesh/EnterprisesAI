"""MCP tool runtime: call a tool on an MCP server as one end user.

See ``invoke.invoke_tool`` for the full call path and its guarantees.
"""
from __future__ import annotations

from builder.services.tool_runtime.classification import Risk, ToolRisk, classify_tool
from builder.services.tool_runtime.errors import (
    ConfirmationRequired,
    InvalidArguments,
    NotConnected,
    ServerNotAuthorized,
    ToolNotFound,
    ToolRuntimeError,
    ToolTimeout,
    ToolUnavailable,
)
from builder.services.tool_runtime.invoke import (
    ToolCallResult,
    invoke_tool,
    resolve_tool,
    user_home,
    validate_arguments,
)
from builder.services.tool_runtime.results import ToolOutput
from builder.services.tool_runtime.session_pool import get_pool, shutdown_pool

__all__ = [
    "Risk",
    "ToolRisk",
    "classify_tool",
    "ToolRuntimeError",
    "ConfirmationRequired",
    "InvalidArguments",
    "NotConnected",
    "ServerNotAuthorized",
    "ToolNotFound",
    "ToolTimeout",
    "ToolUnavailable",
    "ToolCallResult",
    "ToolOutput",
    "invoke_tool",
    "resolve_tool",
    "user_home",
    "validate_arguments",
    "get_pool",
    "shutdown_pool",
]
