"""Draft a whole agent or workflow from a description. Nothing is saved:
the person reviews the draft (on the canvas) and saves it through the normal
agent/workflow endpoints, which run every check again.

Workflow drafting, as in the AI Marketplace, is two passes:
1. the model designs the graph's shape (steps, their identities, lines);
2. each step's tools are found — agent steps from their ``needs``, tool
   steps from their ``need`` — by hybrid search + a pick from the shortlist.
If the shape breaks a structural rule, the problems go back to the model
once for a fix before anything else happens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.assist import prompts
from builder.assist.llm import AssistUnavailable, Usage, ask_json
from builder.assist.tools import Candidate, pick_agent_tools, pick_tool
from builder.graph.schema import NODE_TYPES, TRIGGER_TYPES, WorkflowConfig, WorkflowEdge, WorkflowNode
from builder.graph.validation import GraphProblem, validate_graph
from builder.workflows.scheduler import build_graph

MAX_NODES = 12
X_GAP, Y_GAP = 300, 170


@dataclass
class Draft:
    data: dict
    tools: dict[str, list[dict]] = field(default_factory=dict)  # step id ("agent" for an agent draft) -> its tools
    problems: list[GraphProblem] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def needs_connection(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for tools in self.tools.values():
            for t in tools:
                if not t["connected"]:
                    seen.setdefault(t["server_id"], {"server_id": t["server_id"], "server_name": t["server_name"]})
        return list(seen.values())

    def as_response(self) -> dict:
        return {
            **self.data,
            "tools": self.tools,
            "problems": [p.as_dict() for p in self.problems],
            "needs_connection": self.needs_connection(),
            "usage": {"prompt_tokens": self.usage.prompt_tokens, "completion_tokens": self.usage.completion_tokens},
        }


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def agent_spec(raw: dict) -> dict:
    name = _text(raw.get("name") or raw.get("agent") or raw.get("role"), 255) or "Assistant"
    role = _text(raw.get("role"), 255) or name
    goal = _text(raw.get("goal") or raw.get("description") or raw.get("needs"), 4000) or role
    return {
        "name": name,
        "role": role,
        "goal": goal,
        "instructions": _text(raw.get("instructions") or raw.get("backstory"), 20_000),
        "needs": _text(raw.get("needs"), 1000),
    }


async def draft_agent(db: AsyncSession, user: CurrentUser, description: str) -> Draft:
    usage = Usage()
    spec = agent_spec(await ask_json(prompts.generate_agent_prompt(description), usage))
    # No needs = it works only from what it's told: no tools, rather than guessing from the description.
    chosen = await pick_agent_tools(db, user, f"{spec['role']}: {spec['goal']}\nNeeds: {spec['needs'] or '(none)'}", spec["needs"], usage)
    data = {
        "name": spec["name"], "role": spec["role"], "goal": spec["goal"], "instructions": spec["instructions"],
        "config": {"tool_ids": [c.tool_id for c in chosen]},
    }
    return Draft(data=data, tools={"agent": [c.as_dict() for c in chosen]}, usage=usage)


def layout(nodes: list[dict], edges: list[dict]) -> None:
    """Left-to-right layers by longest forward path from the trigger."""
    if not any(n["type"] in TRIGGER_TYPES for n in nodes):
        return
    graph = build_graph(nodes, edges)
    depth = {graph.trigger: 0}
    order = [graph.trigger]
    for node_id in order:  # grows while iterating: a BFS that relaxes to the longest path
        for edge_id in graph.forward_out[node_id]:
            target = graph.edges[edge_id]["target"]
            if depth.get(target, -1) < depth[node_id] + 1:
                depth[target] = depth[node_id] + 1
                order.append(target)
    rows: dict[int, int] = {}
    for n in nodes:
        d = depth.get(n["id"], max(depth.values(), default=0) + 1)
        n["position"] = {"x": d * X_GAP, "y": rows.get(d, 0) * Y_GAP}
        rows[d] = rows.get(d, 0) + 1


def _shape(raw: dict) -> tuple[str, list[dict], list[dict], list[str]]:
    """The model's graph -> canonical node/edge dicts, plus problems that stop
    it from even being a graph (unknown types, broken edges)."""
    issues: list[str] = []
    nodes: list[dict] = []
    seen: set[str] = set()
    for i, n in enumerate(raw.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        node_id = _text(n.get("id"), 60) or f"n{i + 1}"
        if node_id in seen:
            node_id = f"{node_id}_{i}"
        seen.add(node_id)
        ntype = _text(n.get("type"), 40)
        if ntype == "notification":
            ntype = "tool"
        if ntype not in NODE_TYPES:
            issues.append(f"Step {node_id} has an unknown type '{ntype}'.")
            continue
        node: dict = {"id": node_id, "type": ntype}
        if n.get("label"):
            node["label"] = _text(n["label"], 200)
        if ntype == "agent":
            node["_spec"] = agent_spec(n)
            node["label"] = node.get("label") or node["_spec"]["name"]
        elif ntype == "tool":
            node["need"] = _text(n.get("need") or n.get("name") or n.get("label"), 500)
            node["label"] = node.get("label") or _text(n.get("name"), 200) or None
        elif ntype == "human_approval":
            node["approval_message"] = _text(n.get("approval_message"), 2000) or "Approve this before the workflow continues?"
        elif ntype == "join" and isinstance(n.get("join_policy"), dict):
            node["join_policy"] = n["join_policy"]
        nodes.append({k: v for k, v in node.items() if v is not None})
    ids = {n["id"] for n in nodes}
    edges: list[dict] = []
    for i, e in enumerate(raw.get("edges") or []):
        if not isinstance(e, dict):
            continue
        source, target = _text(e.get("source"), 60), _text(e.get("target"), 60)
        if source not in ids or target not in ids:
            issues.append(f"Edge {e.get('id') or i} connects to a step that doesn't exist ({source} -> {target}).")
            continue
        edge = {"id": f"e{len(edges) + 1}", "source": source, "target": target}
        if e.get("condition"):
            edge["condition"] = _text(e["condition"], 200)
        edges.append(edge)
    name = _text(raw.get("name"), 120) or "New workflow"
    return name, nodes, edges, issues


def _structural(nodes: list[dict], edges: list[dict]) -> list[str]:
    try:
        wn = [WorkflowNode.model_validate({k: v for k, v in n.items() if not k.startswith("_")}) for n in nodes]
        we = [WorkflowEdge.model_validate(e) for e in edges]
    except ValidationError as exc:
        return [str(err["msg"]) for err in exc.errors(include_url=False)][:5]
    # Agents and tools aren't chosen yet at this point — that's the next pass.
    return [p.message for p in validate_graph(wn, we) if p.code not in ("agent_missing", "tool_missing")]


async def draft_workflow(
    db: AsyncSession, user: CurrentUser, description: str, *, allow_parallel: bool = True
) -> Draft:
    usage = Usage()
    raw = await ask_json(prompts.generate_graph_prompt(description, allow_parallel=allow_parallel, max_nodes=MAX_NODES), usage, max_tokens=4000)
    name, nodes, edges, issues = _shape(raw)
    issues += _structural(nodes, edges)
    if issues:  # one repair round with the problems spelled out
        raw = await ask_json(prompts.fix_graph_prompt(json.dumps(raw), issues), usage, max_tokens=4000)
        name, nodes, edges, issues = _shape(raw)
        issues += _structural(nodes, edges)
    if not nodes:
        raise AssistUnavailable("The AI couldn't design a workflow from that description. Try describing the steps.")
    if len(nodes) > MAX_NODES * 2:
        raise AssistUnavailable("The AI designed far too many steps. Try a simpler description.")

    tools: dict[str, list[dict]] = {}
    problems: list[GraphProblem] = [GraphProblem("draft", message) for message in issues]
    agent_steps = [n for n in nodes if n["type"] == "agent"]
    for index, node in enumerate(agent_steps, start=1):
        spec = node.pop("_spec")
        step = (
            f"{spec['role']}: {spec['goal']}\nNeeds: {spec['needs'] or '(nothing outside the text it receives)'}\n\n"
            f'This is step {index} of {len(agent_steps)} in a workflow described as "{description}". A step that '
            "only processes what an earlier step fetched needs no fetching tool, and one before a later save step "
            "doesn't need that destination either."
        )
        chosen: list[Candidate] = await pick_agent_tools(db, user, step, spec["needs"], usage) if spec["needs"] else []
        node["draft_agent"] = {
            "name": spec["name"], "role": spec["role"], "goal": spec["goal"], "instructions": spec["instructions"],
            "config": {"tool_ids": [c.tool_id for c in chosen]},
        }
        tools[node["id"]] = [c.as_dict() for c in chosen]
    for node in nodes:
        if node["type"] != "tool":
            continue
        picked = await pick_tool(db, user, node["need"], f'Context: a step in a workflow described as "{description}".', usage) if node.get("need") else None
        if picked is None:
            problems.append(GraphProblem(
                "tool_not_found",
                f'No available tool can "{node.get("need") or "do this step"}" — connect a system that can, then pick its tool.',
                node["id"],
            ))
            continue
        node["tool_id"] = picked.tool_id
        tools[node["id"]] = [picked.as_dict()]

    layout(nodes, edges)
    data = {"name": name, "nodes": nodes, "edges": edges, "config": WorkflowConfig().model_dump()}
    return Draft(data=data, tools=tools, problems=problems, usage=usage)


__all__ = ["Draft", "draft_agent", "draft_workflow", "layout", "agent_spec"]
