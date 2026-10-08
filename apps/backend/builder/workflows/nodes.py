"""What each kind of workflow step does when it runs.

Every step returns a ``NodeOutcome``: done (with its output text, and for a
condition the line(s) it takes), failed (with a reason), or raises
``Paused`` when a person has to decide. Steps never decide failure policy —
the engine does (retry, skip, tolerate, abort).

Text flow (as in the AI Marketplace): a step's input is its sources' outputs
joined; a condition, join or approval passes its input on; a read tool passes
on what it read, a data-changing tool passes on what it sent; an agent passes
on its answer; the output step shapes the final answer.

Anything decided by an AI on the way (a condition's branch, a tool step's
arguments) is saved on the step's node run before it's acted on, so a
resumed step reuses the decision instead of asking again and getting a
different answer.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy import select

from src.api.deps import CurrentUser

from builder.agents.config import AgentConfig, merge_config
from builder.agents.runtime import AgentContext, AgentFailed, run_agent
from builder.agents.tools import resolve_agent_tools
from builder.graph.condition_rules import eval_rule, normalize_condition_config
from builder.graph.output_config import normalize_output_config
from builder.graph.schema import ToolApprovalPolicy
from builder.models import BuilderApproval, BuilderNodeRun
from builder.runs import states
from builder.runs.db import session_factory
from builder.runs.tool_calls import CallSite, Paused, ledgered_call
from builder.services.tool_runtime import classify_tool
from builder.services.tool_runtime.errors import InvalidArguments
from builder.workflows import text as T
from builder.workflows.scheduler import Graph

logger = logging.getLogger("builder.workflows.nodes")

KIND_MISSING_INPUT = states.KIND_MISSING_INPUT


@dataclass
class NodeOutcome:
    ok: bool
    output: str = ""
    error: str | None = None
    take: set[str] | None = None  # condition: targets to go on to
    final: bool = False  # output step: this is the run's answer
    sources: list[str] = field(default_factory=list)
    never_skip: bool = False  # a person said no: don't paper over it with "skip"
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class StepContext:
    run_id: str
    node: dict
    node_run_id: str
    attempt: int
    user: CurrentUser
    graph: Graph
    input_text: str
    parts: list[tuple[str, str]]
    original_input: str
    failed_inputs: list[str]
    agents: dict[str, dict]
    approvals: ToolApprovalPolicy
    emit: Callable[..., Awaitable[None]]

    @property
    def node_id(self) -> str:
        return self.node["id"]


# ── Small model calls (conditions, tool arguments, output shaping) ───────────


async def quick_llm(prompt: str, *, json_mode: bool = False, max_tokens: int = 1500) -> tuple[str, int, int]:
    from apps.llm_gateway.types import CompletionRequest, Message, Role

    from builder.agents import runtime

    request = CompletionRequest(
        messages=[Message(role=Role.USER, content=prompt)],
        temperature=0.0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"} if json_mode else None,
    )
    response = await runtime._gateway().complete(request)
    usage = response.usage
    return response.content or "", usage.prompt_tokens or 0, usage.completion_tokens or 0


async def _node_state(ctx: StepContext) -> dict:
    async with session_factory() as db:
        node_run = await db.get(BuilderNodeRun, ctx.node_run_id)
        return dict(node_run.state or {})


async def _save_node_state(ctx: StepContext, **values) -> None:
    async with session_factory() as db:
        node_run = await db.get(BuilderNodeRun, ctx.node_run_id)
        node_run.state = {**(node_run.state or {}), **values}
        await db.commit()


# ── Steps ────────────────────────────────────────────────────────────────────


async def run_trigger(ctx: StepContext, variables: dict) -> NodeOutcome:
    text = ctx.original_input
    if variables:
        lines = "\n".join(f"- {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in variables.items())
        text = f"{text}\n\nInputs:\n{lines}" if text else f"Inputs:\n{lines}"
    return NodeOutcome(ok=True, output=text)


async def run_agent_step(ctx: StepContext) -> NodeOutcome:
    agent = ctx.agents.get(ctx.node.get("agent_id") or "")
    if agent is None:
        return NodeOutcome(ok=False, error="The agent for this step is missing from the run's definition.")
    config = AgentConfig.model_validate(merge_config(agent.get("config") or {}, ctx.node.get("config_overrides") or {}))
    # The stricter of the agent's and the workflow's approval rules applies.
    approvals = ToolApprovalPolicy(
        read=config.approvals.read or ctx.approvals.read,
        edit=config.approvals.edit or ctx.approvals.edit,
        delete=config.approvals.delete or ctx.approvals.delete,
    )
    if ctx.input_text.strip() and ctx.input_text.strip() != ctx.original_input.strip():
        task = f"The request: {ctx.original_input}\n\nInput from the previous step:\n{ctx.input_text}"
    else:
        task = ctx.original_input or ctx.input_text
    agent_ctx = AgentContext(
        run_id=ctx.run_id, node_run_id=ctx.node_run_id, node_id=ctx.node_id, attempt=ctx.attempt,
        user=ctx.user, agent=agent, config=config, input_text=task, approvals=approvals, emit=ctx.emit,
    )
    try:
        result = await run_agent(agent_ctx)
    except AgentFailed as exc:
        return NodeOutcome(ok=False, error=str(exc))
    return NodeOutcome(
        ok=True, output=result.text, sources=result.sources,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
    )


async def _map_arguments(tool, text: str) -> tuple[dict, int, int]:
    """The step's text -> the tool's arguments (ported from the Marketplace's
    ``_map_text_to_tool_arguments``): text-like fields get the text itself; the
    rest come from one model call; identifiers (emails, phones, URLs, channels)
    are kept only if they really appear in the text."""
    props = (tool.input_schema or {}).get("properties") or {}
    if not props:
        return {}, 0, 0
    required = set((tool.input_schema or {}).get("required") or [])
    result = {k: text for k in props if T.is_content_field(k)}
    llm_props = {k: v for k, v in props.items() if k not in result}
    pt = ct = 0
    if llm_props:
        ident = {k for k in llm_props if T.identifier_kind(k)}
        lines = "\n".join(
            f'- "{k}"{" (REQUIRED)" if k in required else " (optional)"}'
            f'{" — REAL VALUE ONLY, see rule below" if k in ident else ""}: '
            f'{(v or {}).get("description") or (v or {}).get("type") or "value"}'
            for k, v in llm_props.items()
        )
        prompt = T.tool_arguments_prompt(
            tool.tool_name, tool.description, lines,
            T.REQUIRED_FIELDS_NOTE if (required & set(llm_props)) - ident else "",
            T.IDENTIFIER_FIELDS_NOTE if ident else "", text,
        )
        try:
            raw, pt, ct = await quick_llm(prompt, json_mode=True, max_tokens=600)
            parsed = json.loads(T.strip_json_fence(raw))
            if isinstance(parsed, dict):
                result.update({k: v for k, v in parsed.items() if k in llm_props})
        except Exception as exc:  # noqa: BLE001 — no mapping: required fields are asked for instead
            logger.warning("tool-argument mapping failed for %s: %s", tool.tool_name, exc)
    for k in list(result):
        kind = T.identifier_kind(k)
        if kind is None or T.is_content_field(k):
            continue
        cleaned = T.checked_identifier(kind, result[k], text)
        if cleaned is None:
            result.pop(k)
        else:
            result[k] = cleaned
    return result, pt, ct


def _missing(schema: dict | None, arguments: dict) -> list[str]:
    required = (schema or {}).get("required") or []
    return [k for k in required if arguments.get(k) in (None, "", [], {})]


async def run_tool_step(ctx: StepContext) -> NodeOutcome:
    async with session_factory() as db:
        tools = await resolve_agent_tools(db, [ctx.node.get("tool_id") or ""])
    if not tools:
        return NodeOutcome(ok=False, error="This step's tool is no longer available.")
    tool = tools[0]
    saved = await _node_state(ctx)
    pt = ct = 0
    if "arguments" not in saved:
        source_text = ctx.node.get("message_template") or ctx.input_text
        arguments, pt, ct = await _map_arguments(tool, source_text)
        arguments.update(ctx.node.get("tool_args") or {})
        await _save_node_state(ctx, arguments=arguments)
    else:
        arguments = saved["arguments"]

    # A person may have filled in what was missing or invalid.
    async with session_factory() as db:
        asks = (
            await db.execute(
                select(BuilderApproval).where(
                    BuilderApproval.run_id == ctx.run_id, BuilderApproval.node_id == ctx.node_id,
                    BuilderApproval.kind == KIND_MISSING_INPUT,
                ).order_by(BuilderApproval.created_at)
            )
        ).scalars().all()
    asks = [a for a in asks if (a.payload or {}).get("attempt") == ctx.attempt]
    for ask in asks:
        if ask.status == states.APPROVAL_PENDING:
            raise Paused(ask.id)
        if ask.status == states.APPROVAL_EDITED and ask.edited_input:
            arguments = {**arguments, **ask.edited_input}
        elif ask.status not in states.APPROVAL_YES:
            return NodeOutcome(ok=False, error="Stopped: the missing details for this step weren't provided.", never_skip=True)

    problems: list[str] = []
    missing = _missing(tool.input_schema, arguments)
    if not missing:
        try:
            from builder.services.tool_runtime import validate_arguments

            validate_arguments(tool.input_schema, arguments)
        except InvalidArguments as exc:
            problems = exc.errors
    if missing or problems:
        async with session_factory() as db:
            ask = BuilderApproval(
                run_id=ctx.run_id, tenant_id=ctx.user.tenant_id, owner_id=ctx.user.id, kind=KIND_MISSING_INPUT,
                node_id=ctx.node_id, tool_name=tool.tool_name, risk=classify_tool(tool.tool_name, tool.annotations).risk,
                payload={
                    "attempt": ctx.attempt, "server_name": tool.server_name, "tool_name": tool.tool_name,
                    "missing": missing, "errors": problems, "arguments": arguments, "input_schema": tool.input_schema,
                    "message": (
                        f"{tool.tool_name} needs {', '.join(missing)} — it isn't in the workflow's text. Fill it in to continue."
                        if missing else f"{tool.tool_name}'s arguments need fixing: {'; '.join(problems)}"
                    ),
                },
            )
            db.add(ask)
            await db.commit()
        await ctx.emit("approval_requested", approval_id=ask.id, kind=KIND_MISSING_INPUT, tool=tool.tool_name, node_id=ctx.node_id)
        raise Paused(ask.id)

    site = CallSite(
        run_id=ctx.run_id, node_run_id=ctx.node_run_id, node_id=ctx.node_id, user=ctx.user,
        approvals=ctx.approvals, timeout=float((ctx.node.get("config_overrides") or {}).get("timeout_seconds") or 60),
        requester=f'Workflow step "{ctx.graph.label(ctx.node_id)}"', emit=ctx.emit,
    )
    outcome = await ledgered_call(site, tool, f"{ctx.node_id}:a{ctx.attempt}:tool", arguments)
    if outcome.declined:
        return NodeOutcome(ok=False, error=f"Stopped: {outcome.text}", never_skip=True, prompt_tokens=pt, completion_tokens=ct)
    if outcome.is_error:
        return NodeOutcome(ok=False, error=f"{tool.tool_name} failed: {outcome.error or outcome.text[:500]}", prompt_tokens=pt, completion_tokens=ct)
    # What a step after this one works with: what was read, or what was sent.
    passes_on = outcome.text if classify_tool(tool.tool_name, tool.annotations).risk == "read" else ctx.input_text
    return NodeOutcome(ok=True, output=passes_on, prompt_tokens=pt, completion_tokens=ct)


async def run_condition(ctx: StepContext) -> NodeOutcome:
    out_edges = [ctx.graph.edges[e] for e in ctx.graph.out_edges[ctx.node_id]]
    saved = await _node_state(ctx)
    if "take" in saved:
        return NodeOutcome(ok=True, output=ctx.input_text, take=set(saved["take"]))
    cfg = normalize_condition_config(ctx.node.get("condition_config"), out_edges)
    targets = [e["target"] for e in out_edges]
    pt = ct = 0

    def fallback() -> str:
        if cfg["default_branch"] in targets:
            return cfg["default_branch"]
        for e in out_edges:
            unlabelled = not (e.get("condition") or "").strip()
            if (unlabelled if cfg["mode"] == "ai" else e["target"] not in cfg["rules"]):
                return e["target"]
        return targets[0]

    chosen: str | None = None
    if cfg["mode"] == "rule":
        chosen = next((e["target"] for e in out_edges if e["target"] in cfg["rules"] and eval_rule(cfg["rules"][e["target"]], ctx.input_text)), None)
    else:
        labelled = [e for e in out_edges if (e.get("condition") or "").strip()]
        if len(labelled) == 1 and len(out_edges) == 1:
            chosen = labelled[0]["target"]
        elif labelled:
            has_other_way = bool(cfg["default_branch"]) or len(labelled) < len(out_edges)
            options = "\n".join(f'- "{e["condition"]}"' for e in labelled)
            try:
                raw, pt, ct = await quick_llm(
                    T.condition_branch_prompt(options, ctx.input_text, criteria=cfg["instructions"], allow_none=has_other_way),
                    json_mode=True, max_tokens=100,
                )
                picked = str(json.loads(T.strip_json_fence(raw)).get("label") or "").strip().lower()
                chosen = next((e["target"] for e in labelled if e["condition"].strip().lower() == picked), None)
            except Exception as exc:  # noqa: BLE001 — fall back to matching the label in the text
                logger.warning("condition classification failed on %s: %s", ctx.node_id, exc)
                lowered = (ctx.input_text or "").lower()
                chosen = next((e["target"] for e in labelled if e["condition"].strip().lower() in lowered), None)
    chosen = chosen or fallback()
    await _save_node_state(ctx, take=[chosen])
    label = next((e.get("condition") for e in out_edges if e["target"] == chosen), None)
    await ctx.emit("condition", node_id=ctx.node_id, branch=label or chosen, target=chosen)
    return NodeOutcome(ok=True, output=ctx.input_text, take={chosen}, prompt_tokens=pt, completion_tokens=ct)


async def run_join(ctx: StepContext) -> NodeOutcome:
    policy = ctx.node.get("join_policy") or {}
    mode = policy.get("mode") or "all"
    succeeded, failed = len(ctx.parts), len(ctx.failed_inputs)
    if mode == "all" and failed:
        return NodeOutcome(ok=False, error=f"{failed} branch(es) feeding this join failed: {', '.join(ctx.failed_inputs)}.")
    if mode == "any" and not succeeded:
        return NodeOutcome(ok=False, error="None of the branches feeding this join produced a result.")
    if mode == "count" and succeeded < (policy.get("min_required") or 1):
        return NodeOutcome(ok=False, error=f"Only {succeeded} branch(es) succeeded; this join needs {policy.get('min_required')}.")
    return NodeOutcome(ok=True, output=ctx.input_text)


async def run_human_approval(ctx: StepContext) -> NodeOutcome:
    async with session_factory() as db:
        asks = (
            await db.execute(
                select(BuilderApproval).where(
                    BuilderApproval.run_id == ctx.run_id, BuilderApproval.node_id == ctx.node_id,
                    BuilderApproval.kind == states.KIND_HUMAN_STEP,
                )
            )
        ).scalars().all()
        ask = next((a for a in asks if (a.payload or {}).get("attempt") == ctx.attempt), None)
        if ask is None:
            ask = BuilderApproval(
                run_id=ctx.run_id, tenant_id=ctx.user.tenant_id, owner_id=ctx.user.id, kind=states.KIND_HUMAN_STEP,
                node_id=ctx.node_id,
                payload={
                    "attempt": ctx.attempt, "step": ctx.graph.label(ctx.node_id),
                    "message": ctx.node.get("approval_message") or "Review this before the workflow continues.",
                    "text": ctx.input_text,
                },
            )
            db.add(ask)
            await db.commit()
            await ctx.emit("approval_requested", approval_id=ask.id, kind=states.KIND_HUMAN_STEP, node_id=ctx.node_id)
            raise Paused(ask.id)
    if ask.status == states.APPROVAL_PENDING:
        raise Paused(ask.id)
    if ask.status not in states.APPROVAL_YES:
        return NodeOutcome(ok=False, error="Workflow stopped: the approval step was rejected.", never_skip=True)
    edited = (ask.edited_input or {}).get("text") if ask.status == states.APPROVAL_EDITED else None
    return NodeOutcome(ok=True, output=edited if isinstance(edited, str) and edited.strip() else ctx.input_text)


async def run_output(ctx: StepContext) -> NodeOutcome:
    saved = await _node_state(ctx)
    if "final" in saved:
        return NodeOutcome(ok=True, output=saved["final"], final=True)
    oc = normalize_output_config(ctx.node.get("output_config"))
    texts = [t for _, t in ctx.parts if t]
    text = "\n\n".join(texts) if texts else ctx.original_input
    fmt, language = oc["format"], oc["language"]
    pt = ct = 0

    async def rewrite(prompt: str, current: str, *, json_mode: bool = False) -> str:
        nonlocal pt, ct
        try:
            out, p, c = await quick_llm(prompt, json_mode=json_mode, max_tokens=4000)
            pt, ct = pt + p, ct + c
            return out.strip() or current
        except Exception as exc:  # noqa: BLE001 — shaping never fails the run; the plain answer goes out
            logger.warning("output shaping failed on %s: %s", ctx.node_id, exc)
            return current

    composed = False
    if fmt in ("markdown", "text") and oc["compose"] == "auto" and len(texts) > 1:
        before = text
        text = await rewrite(T.output_compose_prompt(texts, ctx.original_input, language), text)
        composed = text != before
    if fmt == "formatted":
        text = await rewrite(T.output_formatted_prompt(text, oc["sections"], language), text)
    elif fmt == "json":
        shaped = await rewrite(T.output_json_prompt(text, language), text, json_mode=True)
        try:
            text = json.dumps(json.loads(T.strip_json_fence(shaped)), ensure_ascii=False, indent=2)
        except ValueError:
            pass  # not JSON after all: the markdown answer goes out
    elif language and not composed:
        text = await rewrite(T.output_language_prompt(text, language), text)
    if fmt == "text":
        text = T.strip_markdown(text)
    if fmt != "json":
        text = T.with_header_footer(text, oc["header"], oc["footer"])
    await _save_node_state(ctx, final=text)
    return NodeOutcome(ok=True, output=text, final=True, prompt_tokens=pt, completion_tokens=ct)


RUNNERS = {
    "agent": run_agent_step,
    "tool": run_tool_step,
    "condition": run_condition,
    "join": run_join,
    "human_approval": run_human_approval,
    "output": run_output,
}

__all__ = ["NodeOutcome", "StepContext", "Paused", "RUNNERS", "run_trigger", "quick_llm", "KIND_MISSING_INPUT"]
