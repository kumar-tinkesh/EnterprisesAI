"""Run one agent: model turns and tool calls until it answers.

    run_agent(ctx) -> AgentResult        (raises Paused / AgentFailed)

The loop is a function of what's saved, so it can stop anywhere and pick up
again — after an approval, or on another worker after a crash:

* **Checkpoint per model turn.** The conversation (messages, turn count,
  token usage) is saved on the node run after every model reply and every
  tool result. Resuming replays nothing: it continues from the last saved
  message.
* **Tool-call ledger.** Each call has a deterministic key (node, attempt,
  turn, index) and a ``BuilderToolCall`` row written *before* it is sent.
  On resume a finished call's stored result is reused; a call left
  ``started`` (the worker died mid-call) is re-run only if it's a read tool —
  a data-changing one becomes an ``uncertain_call`` approval: "this may
  already have run — run it again?"
* **Approvals.** The agent's approval policy (read / edit / delete) decides
  which calls need a yes first. The run then pauses (``Paused``) and the
  worker lets go; the decision re-queues it.
* **Guardrails** (``builder.guardrails``, when the agent has any on): the
  request is checked before the first model call, each tool result before
  the model reads it, and the answer once — its outcome is checkpointed, so a
  resume never re-runs (or re-bills) the answer checks. Every finding is
  emitted as a ``guardrail`` event and returned on the result.

Model requests go through the LLM gateway with the agent's retry settings.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


from src.api.deps import CurrentUser

from builder.agents.config import AgentConfig
from builder.agents.prompts import system_prompt
from builder.agents.tools import KNOWLEDGE_TOOL, AgentTool, function_definitions, resolve_agent_tools, search_knowledge
from builder.graph.schema import ToolApprovalPolicy
from builder.guardrails.engine import MAX_EVIDENCE, Flag, check_input, check_output, check_tool_result
from builder.models import BuilderNodeRun
from builder.runs.db import session_factory
from builder.runs.tool_calls import CallSite, Paused, ledgered_call
from builder.services.tool_runtime.errors import InvalidArguments

logger = logging.getLogger("builder.agents.runtime")

# What the model sees of one tool result (the ledger keeps the full capped output).
MAX_TOOL_TEXT_FOR_MODEL = 20_000
_RETRYABLE = {
    "rate_limit": ("rate limit", "ratelimit", "429", "quota", "resource_exhausted"),
    "timeout": ("timeout", "timed out", "deadline"),
    "server": ("internal server", "500", "502", "503", "504", "unavailable", "overloaded"),
    "provider": ("provider", "upstream", "connection", "network"),
}


class AgentFailed(Exception):
    """The agent can't finish (model unavailable, a tool failed with on_failure=stop, …)."""


class GuardrailBlocked(AgentFailed):
    """A guardrail stopped the run (the request was refused, or the answer withheld)."""

    def __init__(self, message: str, flags: list[dict]):
        super().__init__(message)
        self.flags = flags


@dataclass
class AgentContext:
    run_id: str
    node_run_id: str
    node_id: str
    attempt: int
    user: CurrentUser
    agent: dict
    config: AgentConfig
    input_text: str
    approvals: ToolApprovalPolicy
    emit: Callable[..., Awaitable[None]]
    # A test run (see builder.runs.tool_calls.CallSite.dry_run).
    dry_run: bool = False
    # How much answer the person asked for: "auto" | "short" | "detailed".
    depth: str = "auto"


@dataclass
class AgentResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    sources: list[str] = field(default_factory=list)
    # What the guardrails found or did (builder.guardrails.engine.Flag dicts).
    guardrails: list[dict] = field(default_factory=list)


def _gateway():
    from vendor.services.llm_gateway_client import get_gateway

    return get_gateway()


def _is_retryable(exc: BaseException, retry_on: list[str]) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(needle in text for kind in retry_on for needle in _RETRYABLE.get(kind, ()))


def _to_gateway_messages(messages: list[dict]):
    from apps.llm_gateway.types import Message, Role, ToolCall

    out = []
    for m in messages:
        calls = [ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in m.get("tool_calls") or []]
        out.append(Message(role=Role(m["role"]), content=m.get("content") or "", tool_call_id=m.get("tool_call_id"), tool_calls=calls or None))
    return out


async def _complete(ctx: AgentContext, messages: list[dict], tool_defs: list[dict] | None):
    from apps.llm_gateway.types import CompletionRequest, ToolDefinition

    llm, rel = ctx.config.llm, ctx.config.reliability
    models = [ctx.agent.get("llm_model") or None]
    if rel.fallback_model:
        models.append(rel.fallback_model)
    last_error: BaseException | None = None
    for model in models:
        request = CompletionRequest(
            messages=_to_gateway_messages(messages),
            model=model,
            temperature=llm.temperature if llm.temperature is not None else 0.3,
            max_tokens=llm.max_output_tokens,
            stop=llm.stop_sequences or None,
            tools=[ToolDefinition(**d) for d in tool_defs] if tool_defs else None,
        )
        for attempt in range(1 + rel.retries):
            try:
                return await asyncio.wait_for(
                    _gateway().complete(request, provider=ctx.agent.get("llm_provider") or None),
                    timeout=rel.request_timeout_seconds or 300,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — classified below
                last_error = exc
                if attempt < rel.retries and _is_retryable(exc, rel.retry_on):
                    from builder.config import get_builder_settings

                    await asyncio.sleep(get_builder_settings().AGENT_MODEL_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                break
    raise AgentFailed(f"The model request failed: {last_error}")


async def _checkpoint(ctx: AgentContext, state: dict) -> None:
    async with session_factory() as db:
        node_run = await db.get(BuilderNodeRun, ctx.node_run_id)
        node_run.state = state
        node_run.prompt_tokens = state["prompt_tokens"]
        node_run.completion_tokens = state["completion_tokens"]
        await db.commit()


def _model_text(text: str) -> str:
    if len(text) <= MAX_TOOL_TEXT_FOR_MODEL:
        return text
    return text[:MAX_TOOL_TEXT_FOR_MODEL] + f"\n… [{len(text) - MAX_TOOL_TEXT_FOR_MODEL} more characters not shown]"


async def _note(ctx: AgentContext, state: dict, flags: list[Flag]) -> None:
    """Keep guardrail findings on the run's state and show them as they happen."""
    for f in flags:
        state.setdefault("guardrails", []).append(f.as_dict())
        await ctx.emit("guardrail", node_id=ctx.node_id, rule=f.rule, severity=f.severity, message=f.message)


async def _judge(ctx: AgentContext, prompt: str) -> tuple[str, int, int]:
    """One model call for a guardrail check, on the agent's own model."""
    response = await _complete(ctx, [{"role": "user", "content": prompt}], None)
    return response.content or "", response.usage.prompt_tokens or 0, response.usage.completion_tokens or 0


async def _guard_tool_result(ctx: AgentContext, state: dict, tool: str, text: str) -> str:
    text, flags = check_tool_result(text, tool, ctx.config.guardrails)
    await _note(ctx, state, flags)
    return text


async def _run_call(ctx: AgentContext, by_fn: dict[str, AgentTool], turn: int, index: int, call: dict, state: dict) -> str:
    sources: list[str] = state["sources"]
    name = call["name"]
    try:
        arguments = json.loads(call.get("arguments") or "{}")
    except ValueError:
        return "Error: the arguments were not valid JSON. Call the tool again with a JSON object."
    if not isinstance(arguments, dict):
        return "Error: the arguments must be a JSON object."

    if name == KNOWLEDGE_TOOL and ctx.config.knowledge_base_ids:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return "Error: give a query to search for."
        await ctx.emit("tool_call", phase="started", tool=KNOWLEDGE_TOOL, risk="read", node_id=ctx.node_id)
        async with session_factory() as db:
            text, passages = await search_knowledge(db, tenant_id=ctx.user.tenant_id, kb_ids=ctx.config.knowledge_base_ids, query=query)
        sources.extend(p["filename"] for p in passages)
        if ctx.config.guardrails.groundedness:
            evidence = state.setdefault("evidence", [])
            evidence.extend(p["content"][:2000] for p in passages if p["content"] not in evidence)
            del evidence[:-MAX_EVIDENCE]
        await ctx.emit("tool_call", phase="finished", tool=KNOWLEDGE_TOOL, is_error=False, node_id=ctx.node_id)
        return await _guard_tool_result(ctx, state, "the knowledge base", text)

    tool = by_fn.get(name)
    if tool is None:
        return f"Error: there is no tool named {name}."
    site = CallSite(
        run_id=ctx.run_id, node_run_id=ctx.node_run_id, node_id=ctx.node_id, user=ctx.user,
        approvals=ctx.approvals, timeout=ctx.config.tools.timeout_seconds,
        requester=ctx.agent.get("name") or "The agent", emit=ctx.emit, dry_run=ctx.dry_run,
    )
    try:
        outcome = await ledgered_call(site, tool, f"{ctx.node_id}:a{ctx.attempt}:t{turn}:c{index}", arguments)
    except InvalidArguments as exc:
        return "Error: " + exc.message + " " + "; ".join(exc.errors)
    if outcome.is_error and not outcome.declined and ctx.config.tools.on_failure == "stop":
        raise AgentFailed(f"{tool.tool_name} failed: {outcome.error or outcome.text[:500]}")
    return await _guard_tool_result(ctx, state, tool.tool_name, _model_text(outcome.text))


async def run_agent(ctx: AgentContext) -> AgentResult:
    async with session_factory() as db:
        node_run = await db.get(BuilderNodeRun, ctx.node_run_id)
        state: dict[str, Any] = dict(node_run.state or {})
        tools = await resolve_agent_tools(db, ctx.config.tool_ids)
    by_fn = {t.function_name: t for t in tools}
    has_knowledge = bool(ctx.config.knowledge_base_ids)
    tool_defs = function_definitions(tools, with_knowledge=has_knowledge)

    guard = ctx.config.guardrails
    if not state.get("messages"):
        checked = check_input(ctx.input_text, guard)
        if checked.blocked:
            await _note(ctx, {}, checked.flags)
            raise GuardrailBlocked(checked.blocked, [f.as_dict() for f in checked.flags])
        state = {
            "messages": [
                {"role": "system", "content": system_prompt(ctx.agent, ctx.config, has_tools=bool(tool_defs), has_knowledge=has_knowledge, depth=ctx.depth)},
                {"role": "user", "content": checked.text},
            ],
            "turn": 0,
            "tool_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "sources": [],
            "guardrails": [],
        }
        await _note(ctx, state, checked.flags)
        await _checkpoint(ctx, state)
    messages: list[dict] = state["messages"]
    sources: list[str] = state.setdefault("sources", [])

    while True:
        last = messages[-1]
        if last["role"] == "assistant" and last.get("tool_calls"):
            answered = {m.get("tool_call_id") for m in messages if m["role"] == "tool"}
            for index, call in enumerate(last["tool_calls"]):
                if call["id"] in answered:
                    continue
                text = await _run_call(ctx, by_fn, state["turn"], index, call, state)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
                state["tool_calls"] += 1
                await _checkpoint(ctx, state)
        elif last["role"] == "assistant":
            text = last.get("content") or ""
            if guard.any_on():
                if "final" not in state:  # checked once, then saved: a resume reuses the outcome
                    checked_out = await check_output(text, state.get("evidence") or [], guard, lambda p: _judge(ctx, p))
                    state["prompt_tokens"] += checked_out.prompt_tokens
                    state["completion_tokens"] += checked_out.completion_tokens
                    state["final"] = {"text": checked_out.text, "blocked": checked_out.blocked}
                    await _note(ctx, state, checked_out.flags)
                    await _checkpoint(ctx, state)
                if state["final"]["blocked"]:
                    raise GuardrailBlocked(state["final"]["blocked"], list(state.get("guardrails") or []))
                text = state["final"]["text"]
            return AgentResult(
                text=text,
                prompt_tokens=state["prompt_tokens"],
                completion_tokens=state["completion_tokens"],
                tool_calls=state["tool_calls"],
                sources=list(dict.fromkeys(sources)),
                guardrails=list(state.get("guardrails") or []),
            )

        out_of_budget = state["tool_calls"] >= ctx.config.tools.max_calls
        if out_of_budget and not state.get("budget_note"):
            messages.append({"role": "system", "content": "You have used all the tool calls allowed for this task. Answer now with what you have."})
            state["budget_note"] = True
        response = await _complete(ctx, messages, None if out_of_budget else (tool_defs or None))
        state["turn"] += 1
        state["prompt_tokens"] += response.usage.prompt_tokens or 0
        state["completion_tokens"] += response.usage.completion_tokens or 0
        calls = [
            {"id": tc.id or f"call_{state['turn']}_{i}", "name": tc.name, "arguments": tc.arguments or "{}"}
            for i, tc in enumerate(response.tool_calls or [])
        ]
        message: dict = {"role": "assistant", "content": response.content or ""}
        if calls and not out_of_budget:
            message["tool_calls"] = calls
        messages.append(message)
        await _checkpoint(ctx, state)
        await ctx.emit("agent_turn", turn=state["turn"], node_id=ctx.node_id, tool_calls=[c["name"] for c in message.get("tool_calls", [])])


__all__ = ["AgentContext", "AgentResult", "AgentFailed", "GuardrailBlocked", "Paused", "run_agent"]
