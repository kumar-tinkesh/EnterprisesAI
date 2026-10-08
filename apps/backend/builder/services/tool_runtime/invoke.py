"""Call one MCP tool as one end user.

    invoke_tool(db, user=..., server_id=..., tool_name=..., arguments=...)

Steps, each failing with a specific ``ToolRuntimeError``:

1. The server exists and this user may use it (same rule as their
   self-service connect) — else ``ServerNotAuthorized``.
2. The tool is one the server advertised at verification — ``ToolNotFound``.
3. Risk: a tool that changes data (edit/delete) needs ``confirm=True`` —
   ``ConfirmationRequired``. (Agents and workflows will route this through
   their approval step instead.)
4. Arguments match the tool's JSON Schema — ``InvalidArguments``.
5. The user connected their own account for the server — ``NotConnected``.
6. Their runtime config is resolved (stored credential, OAuth refresh, their
   own device bridge), a pooled session is opened or reused, and the call
   runs under a timeout — ``ToolTimeout`` / ``ToolUnavailable``.

A server that answers with a JSON-RPC error, or a tool that reports
``is_error``, is a normal result with ``output.is_error`` set: the server is
fine, the call just didn't succeed — an agent should see that and adapt.

**Retries.** If the session breaks mid-call, a read tool is retried once on a
fresh session. A tool that changes data is never retried automatically: the
request may already have run, and running it twice could send two emails.
``ToolUnavailable.may_have_run`` tells the caller which case it is.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import exceptions as jsonschema_exceptions
from jsonschema.validators import validator_for
from mcp import types
from mcp.shared.exceptions import MCPError
from mcp.types.jsonrpc import CONNECTION_CLOSED
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.mcp_client import open_mcp_session
from vendor.services.mcp_service.connection import build_runtime_config
from vendor.services.mcp_service.crud import get_mcp_server, is_server_visible_to_user

from builder.config import get_builder_settings
from builder.services.tool_runtime.classification import ToolRisk, classify_tool
from builder.services.tool_runtime.errors import (
    ConfirmationRequired,
    InvalidArguments,
    NotConnected,
    ServerNotAuthorized,
    ToolNotFound,
    ToolTimeout,
    ToolUnavailable,
)
from builder.services.tool_runtime.results import ToolOutput, normalize_result
from builder.services.tool_runtime.session_pool import get_pool

logger = logging.getLogger("builder.tool_runtime")


def _connection_closed(exc: MCPError) -> bool:
    """The SDK's own "the connection closed" error, not a reply from the server.

    Servers may legitimately answer with -32000 (the generic JSON-RPC server
    error), so the code alone isn't enough; the SDK raises it with this exact
    message when the transport goes away mid-request.
    """
    return exc.code == CONNECTION_CLOSED and exc.message == "Connection closed"

_MAX_SCHEMA_ERRORS = 10


@dataclass
class ToolCallResult:
    server_id: str
    server_name: str
    tool_name: str
    risk: ToolRisk
    output: ToolOutput
    duration_ms: int
    attempts: int


async def resolve_tool(
    db: AsyncSession, *, user: CurrentUser, server_id: str, tool_name: str
) -> tuple[VendorMCPServer, MCPTool]:
    server = await get_mcp_server(db, server_id)
    if server is None or not await is_server_visible_to_user(db, user=user, server=server):
        raise ServerNotAuthorized("MCP server not found.")
    tool = (
        await db.execute(
            select(MCPTool).where(MCPTool.mcp_server_id == server.id, MCPTool.name == tool_name)
        )
    ).scalars().first()
    if tool is None:
        raise ToolNotFound(f"{server.name} has no tool named {tool_name!r}.")
    return server, tool


def validate_arguments(schema: dict | None, arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise InvalidArguments("Arguments must be a JSON object.", ["(root): must be an object"])
    if not isinstance(schema, dict) or not schema:
        return
    try:
        cls = validator_for(schema)
        cls.check_schema(schema)
    except jsonschema_exceptions.SchemaError:
        logger.warning("tool input_schema is not a valid JSON Schema; skipping validation")
        return
    errors = sorted(cls(schema).iter_errors(arguments), key=lambda e: list(e.absolute_path))
    if errors:
        messages = [
            f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in errors[:_MAX_SCHEMA_ERRORS]
        ]
        raise InvalidArguments("The arguments don't match what this tool expects.", messages)


def user_home(user_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:64] or "anonymous"
    return Path(get_builder_settings().BUILDER_USER_HOME_ROOT) / safe


def _fingerprint(config: dict) -> str:
    # Includes credentials: a reconnect or refreshed token must not reuse a
    # session started with the old ones. Kept in memory only.
    encoded = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


async def invoke_tool(
    db: AsyncSession,
    *,
    user: CurrentUser,
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    confirm: bool = False,
    timeout: float | None = None,
) -> ToolCallResult:
    settings = get_builder_settings()
    arguments = arguments if arguments is not None else {}

    server, tool = await resolve_tool(db, user=user, server_id=server_id, tool_name=tool_name)
    risk = classify_tool(tool.name, tool.annotations)
    if risk.needs_confirmation and not confirm:
        raise ConfirmationRequired(
            f"{tool.name} can change data ({risk.risk}). Confirm to run it.", risk.risk
        )
    validate_arguments(tool.input_schema, arguments)

    if not await mcp_auth.has_user_credential(db, server_id=server.id, user_id=user.id):
        raise NotConnected(f"Connect your {server.name} account before this tool can run.", server.id)
    try:
        config = await build_runtime_config(db, server=server, user_id=user.id, tenant_id=user.tenant_id)
    except mcp_auth.McpAuthError as exc:
        raise NotConnected(str(exc), server.id) from exc
    # Resolution may have refreshed and re-stored an OAuth token.
    await db.commit()

    call_timeout = min(float(timeout or settings.TOOL_CALL_TIMEOUT_SECONDS), settings.TOOL_CALL_MAX_TIMEOUT_SECONDS)
    home = user_home(user.id)
    key = (user.id, server.id, _fingerprint(config))
    pool = get_pool()

    def opener():
        return open_mcp_session(config, home_dir=home, connect_timeout=settings.TOOL_SESSION_CONNECT_TIMEOUT_SECONDS)

    started = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        async with pool.acquire(
            key,
            user_id=user.id,
            label=server.name,
            opener=opener,
            connect_timeout=settings.TOOL_SESSION_CONNECT_TIMEOUT_SECONDS,
        ) as entry:
            transport_error: Exception | None = None
            try:
                raw = await asyncio.wait_for(entry.session.call_tool(tool.name, arguments), timeout=call_timeout)
                output = _to_output(raw, settings.TOOL_RESULT_MAX_CHARS)
                break
            except TimeoutError:
                # The server may be wedged on this call; don't hand the session to the next caller.
                await pool.evict(entry)
                raise ToolTimeout(
                    f"{tool.name} didn't finish within {call_timeout:.0f}s. It may still have run on {server.name}."
                ) from None
            except MCPError as exc:
                if not _connection_closed(exc) and not entry.dead:
                    # A JSON-RPC error *response*: the server is alive and said no.
                    output = ToolOutput(is_error=True, text=exc.message or str(exc))
                    break
                transport_error = exc  # the connection itself closed
            except Exception as exc:  # transport broke mid-call
                transport_error = exc

            await pool.evict(entry)
            logger.warning("tool call transport failure %s/%s: %s", server.name, tool.name, transport_error)
            if risk.risk == "read" and attempts == 1:
                continue
            raise ToolUnavailable(
                f"Lost the connection to {server.name} while {tool.name} was running.",
                may_have_run=True,
            ) from transport_error

    return ToolCallResult(
        server_id=server.id,
        server_name=server.name,
        tool_name=tool.name,
        risk=risk,
        output=output,
        duration_ms=int((time.monotonic() - started) * 1000),
        attempts=attempts,
    )


def _to_output(raw: Any, max_chars: int) -> ToolOutput:
    if isinstance(raw, types.CallToolResult):
        return normalize_result(raw, max_chars=max_chars)
    # e.g. InputRequiredResult: the server wants interactive input (elicitation),
    # which an unattended tool call can't give it.
    kind = type(raw).__name__
    return ToolOutput(is_error=True, text=f"The tool asked for interactive input ({kind}), which isn't supported here.")


__all__ = ["ToolCallResult", "invoke_tool", "resolve_tool", "validate_arguments", "user_home"]
