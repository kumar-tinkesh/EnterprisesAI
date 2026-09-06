"""Phase 4 — fill a tool's arguments from a natural-language query.

This is the "how does the LLM part work" piece requested after Phase 3
(``catalog_engine.get_relevant_tools_semantic``, which only *selects* tool
candidates). Given a query, it:

  1. Reuses Phase 3 to shortlist a few candidate tools (already
     access-filtered + semantically ranked — no extra work here).
  2. Hands those candidates to a chat LLM as OpenAI-style function
     definitions (``ToolDefinition``, one per candidate) and asks it to
     call the single best one, with arguments matching that tool's
     ``input_schema``.
  3. Returns the model's chosen tool + parsed arguments as data.

It never calls the MCP server itself — ``mcp_client.MCPClient`` has no
invoke/execute method yet, and this module doesn't add one. The output here
is exactly what a future "actually call it" step would need as input.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from vendor.models import MCPTool, VendorMCPServer
from user.services.catalog_engine import get_relevant_tools_semantic
from vendor.services.llm_gateway_client import get_gateway

logger = logging.getLogger("user.tool_call_planner")

_SYSTEM_PROMPT = (
    "You select and fill parameters for exactly ONE tool to satisfy the "
    "user's request. This is a PROPOSAL only — nothing is executed "
    "automatically, a human reviews it before anything happens. So: if any "
    "of the available tools is a plausible match for what the user is "
    "asking, select it and fill in every parameter with your best-guess "
    "value, using a reasonable placeholder for any detail the user did not "
    "specify (e.g. a generic message, a placeholder id) — do not leave it "
    "unselected just because some details are missing. Only decline (call "
    "no tool) when none of the available tools are even conceptually "
    "related to what the user asked for."
)

_NAME_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _sanitize_name(name: str) -> str:
    return _NAME_SAFE_RE.sub("_", name).strip("_")[:64] or "tool"


def _unique_function_name(
    tool_name: str, server_name: str, taken: dict[str, Any]
) -> str:
    """Return a name unique among ``taken`` — OpenAI-style function names
    must be unique within one request's tool list, but two different MCP
    servers can legally expose a same-named tool (e.g. both have "search")."""
    base = _sanitize_name(tool_name)
    if base not in taken:
        return base
    qualified = _sanitize_name(f"{server_name}_{tool_name}")
    if qualified not in taken:
        return qualified
    n = 2
    while f"{qualified}_{n}" in taken:
        n += 1
    return f"{qualified}_{n}"


@dataclass
class ToolCallPlan:
    """One resolved, argument-filled — but NOT yet invoked — tool call."""

    tool_id: str
    tool_name: str
    server_id: str
    server_name: str
    arguments: dict[str, Any]
    input_schema: Optional[dict[str, Any]]
    model: str
    raw_arguments: str


@dataclass
class ToolCallPlanResult:
    """Outcome of :func:`plan_tool_call`. ``plan`` is ``None`` when no tool
    call could be produced; ``message`` then explains why (no candidates,
    chat LLM unavailable, or the model declined to call any tool)."""

    plan: Optional[ToolCallPlan]
    candidates_considered: list[str]
    message: Optional[str] = None


async def plan_tool_call(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    top_k_servers: int = 5,
    top_k_tools: int = 3,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ToolCallPlanResult:
    """Select one MCP tool for ``query`` and fill its arguments. Read-only:
    performs no MCP connection and calls no tool."""
    matches = await get_relevant_tools_semantic(
        db,
        user=user,
        query=query,
        top_k_servers=top_k_servers,
        top_k_tools=top_k_tools,
    )
    if not matches:
        return ToolCallPlanResult(
            plan=None,
            candidates_considered=[],
            message="No MCP tool matched this query.",
        )

    from apps.llm_gateway.types import (
        CompletionRequest,
        Message,
        Role,
        ToolDefinition,
    )

    name_map: dict[str, tuple[VendorMCPServer, MCPTool]] = {}
    tool_defs: list[ToolDefinition] = []
    for server, tool, _score in matches:
        fn_name = _unique_function_name(tool.name, server.name, name_map)
        name_map[fn_name] = (server, tool)
        tool_defs.append(
            ToolDefinition(
                name=fn_name,
                description=f"[{server.name}] {tool.description}".strip(),
                parameters=tool.input_schema or {"type": "object", "properties": {}},
            )
        )

    request = CompletionRequest(
        messages=[
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
            Message(role=Role.USER, content=query),
        ],
        tools=tool_defs,
        tool_choice="auto",
        temperature=0.0,
        model=model,
    )

    try:
        from apps.llm_gateway.exceptions import LLMGatewayError

        resp = await get_gateway().complete(request, provider=provider)
    except LLMGatewayError as exc:
        logger.warning("plan_tool_call: chat LLM unavailable: %s", exc)
        return ToolCallPlanResult(
            plan=None,
            candidates_considered=list(name_map),
            message="Chat LLM unavailable right now.",
        )
    except Exception:
        logger.exception("plan_tool_call: unexpected chat LLM failure")
        return ToolCallPlanResult(
            plan=None,
            candidates_considered=list(name_map),
            message="Chat LLM unavailable right now.",
        )

    if not resp.tool_calls:
        return ToolCallPlanResult(
            plan=None,
            candidates_considered=list(name_map),
            message="Model did not find a confident tool match for this query.",
        )

    call = resp.tool_calls[0]
    match = name_map.get(call.name)
    if match is None:
        return ToolCallPlanResult(
            plan=None,
            candidates_considered=list(name_map),
            message=f"Model referenced an unknown tool ({call.name!r}).",
        )
    server, tool = match

    try:
        arguments = json.loads(call.arguments) if call.arguments else {}
    except json.JSONDecodeError:
        logger.warning("plan_tool_call: non-JSON arguments from model: %r", call.arguments)
        arguments = {}

    plan = ToolCallPlan(
        tool_id=tool.id,
        tool_name=tool.name,
        server_id=server.id,
        server_name=server.name,
        arguments=arguments,
        input_schema=tool.input_schema,
        model=resp.model,
        raw_arguments=call.arguments,
    )
    return ToolCallPlanResult(plan=plan, candidates_considered=list(name_map))


__all__ = ["ToolCallPlan", "ToolCallPlanResult", "plan_tool_call"]
