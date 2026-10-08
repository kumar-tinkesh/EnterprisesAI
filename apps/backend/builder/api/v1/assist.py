"""Builder assistant endpoints (mounted under ``/api/v1/builder``).

    GET  /tools/search?q=          tool picker: hybrid search over the caller's tools
    POST /assist/agent             description -> agent draft (with chosen tools)
    POST /assist/workflow          description -> workflow draft (steps, lines, agents, tools)
    POST /assist/workflow-edit     instruction + the open graph -> edited draft
    POST /assist/improve-text      polish one field's rough text

Drafts are never saved here. The canvas shows them; saving goes through the
agent/workflow endpoints, which check everything again (and turn each new
agent step's ``draft_agent`` into one of the workflow's own agents).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.assist import prompts
from builder.assist.drafts import X_GAP, draft_agent, draft_workflow
from builder.assist.edit import Editor, EditError, resolve
from builder.assist.llm import AssistUnavailable, Usage, ask, ask_json
from builder.assist.tools import search_tools
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
from builder.graph.validation import validate_graph
from builder.models import BuilderAgent
from builder.services.references import workflow_reference_problems

router = APIRouter()


class DescribeRequest(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    allow_parallel: bool = True


class EditRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=4000)
    name: str = Field(default="Workflow", max_length=255)
    nodes: list[dict] = Field(default_factory=list, max_length=200)
    edges: list[dict] = Field(default_factory=list, max_length=500)
    config: dict = Field(default_factory=dict)
    workflow_id: str | None = None


class ImproveRequest(BaseModel):
    field: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=20_000)
    context: str = Field(default="", max_length=4000)


def _unavailable(exc: AssistUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/tools/search")
async def tool_search(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=8, ge=1, le=20),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    return [c.as_dict() for c in await search_tools(db, user, q, top_k_tools=limit)]


@router.post("/assist/agent")
async def assist_agent(payload: DescribeRequest, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    try:
        return (await draft_agent(db, user, payload.description)).as_response()
    except AssistUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/assist/workflow")
async def assist_workflow(payload: DescribeRequest, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    try:
        draft = await draft_workflow(db, user, payload.description, allow_parallel=payload.allow_parallel)
    except AssistUnavailable as exc:
        raise _unavailable(exc) from exc
    return draft.as_response()


def _describe(nodes: list[dict], edges: list[dict], agents: dict[str, dict]) -> tuple[str, str]:
    lines = []
    for n in nodes:
        detail = ""
        if n.get("type") == "agent":
            a = n.get("draft_agent") or agents.get(n.get("agent_id") or "") or {}
            detail = f' "{a.get("name", "?")}" — {a.get("role", "")}: {a.get("goal", "")}'
        elif n.get("type") == "tool":
            detail = f" does: {n.get('need') or n.get('tool_id') or '(no tool yet)'}"
        elif n.get("type") == "human_approval":
            detail = f" asks: {n.get('approval_message') or ''}"
        elif n.get("type") in ("output", "condition", "join"):
            cfg = n.get("output_config") or n.get("condition_config") or n.get("join_policy")
            detail = f" {json.dumps(cfg)}" if cfg else ""
        label = f" ({n['label']})" if n.get("label") else ""
        lines.append(f"- {n.get('id')} [{n.get('type')}]{label}{detail}")
    edge_lines = [
        f"- {e.get('source')} -> {e.get('target')}" + (f' [{e["condition"]}]' if e.get("condition") else "") for e in edges
    ]
    return "\n".join(lines) or "(none)", "\n".join(edge_lines) or "(none)"


def _place_new(nodes: list[dict], edges: list[dict]) -> None:
    """Give steps an edit added (no position yet) a spot beside what they connect to."""
    by_id = {n["id"]: n for n in nodes}
    right = max((n.get("position", {}).get("x", 0) for n in nodes if n.get("position")), default=0)
    for n in nodes:
        if n.get("position"):
            continue
        source = next((by_id[e["source"]] for e in edges if e["target"] == n["id"] and by_id.get(e["source"], {}).get("position")), None)
        if source:
            n["position"] = {"x": source["position"]["x"] + X_GAP, "y": source["position"]["y"] + 60}
        else:
            right += X_GAP
            n["position"] = {"x": right, "y": 0}


@router.post("/assist/workflow-edit")
async def assist_workflow_edit(payload: EditRequest, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent_ids = [n.get("agent_id") for n in payload.nodes if n.get("type") == "agent" and n.get("agent_id")]
    agents = {
        a.id: {"name": a.name, "role": a.role, "goal": a.goal, "instructions": a.instructions, "llm_provider": a.llm_provider,
               "llm_model": a.llm_model, "config": a.config or {}}
        for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(agent_ids), BuilderAgent.tenant_id == user.tenant_id))).scalars()
    } if agent_ids else {}
    node_lines, edge_lines = _describe(payload.nodes, payload.edges, agents)
    usage = Usage()
    prompt = prompts.edit_prompt(payload.name, node_lines, edge_lines, payload.config, payload.instruction)
    try:
        answer = await ask_json(prompt, usage)
        editor = None
        error: str | None = None
        for attempt in range(2):
            ops = answer.get("ops") if isinstance(answer.get("ops"), list) else []
            resolved = await resolve(db, user, ops, payload.nodes, agents, usage, payload.name)
            editor = Editor(payload.name, payload.nodes, payload.edges, payload.config, resolved)
            try:
                editor.apply(ops)
                error = None
                break
            except EditError as exc:
                error = str(exc)
                if attempt == 0:
                    answer = await ask_json(f"{prompt}\n\nYour operations failed: {error}\nReturn corrected operations.", usage)
        if error:
            raise HTTPException(status_code=422, detail=f"Couldn't apply that change: {error}")
    except AssistUnavailable as exc:
        raise _unavailable(exc) from exc

    _place_new(editor.nodes, editor.edges)
    problems = []
    try:
        nodes = [WorkflowNode.model_validate(n) for n in editor.nodes]
        edges = [WorkflowEdge.model_validate(e) for e in editor.edges]
        problems = validate_graph(nodes, edges)
        problems += await workflow_reference_problems(
            db, user, workflow_id=payload.workflow_id, nodes=nodes,
            config=WorkflowConfig.model_validate(editor.config or {}), check_connection=False,
        )
    except Exception as exc:  # a shape pydantic rejects: still return the draft with the reason
        problems = []
        editor.warnings.append(f"The edited workflow has an invalid step: {exc}")
    return {
        "name": editor.name,
        "nodes": editor.nodes,
        "edges": editor.edges,
        "config": editor.config,
        "summary": answer.get("summary"),
        "answer": answer.get("answer"),
        "changes": editor.changes,
        "warnings": editor.warnings,
        "problems": [p.as_dict() for p in problems],
        "tools": editor.new_tools,
        "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens},
    }


@router.post("/assist/improve-text")
async def improve_text(payload: ImproveRequest, user: CurrentUser = Depends(get_end_user)):
    usage = Usage()
    try:
        text = await ask(prompts.improve_text_prompt(payload.field, payload.text, payload.context), usage, json_mode=False, max_tokens=800)
    except AssistUnavailable as exc:
        raise _unavailable(exc) from exc
    return {"text": text.strip().strip('"') or payload.text}
