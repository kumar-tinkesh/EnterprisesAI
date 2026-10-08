"""Structural checks on a workflow graph — no database, no network.

Returns *every* problem rather than stopping at the first, each tied to the
node or edge it's about, so a canvas can mark all of them at once. Ported
from the AI Marketplace's ``api/v1/workflows.py`` (``_validate_graph`` /
``_validate_topology``) with one addition:

* Cycles are allowed — a condition step looping back for another review pass
  is a real pattern — but only if the loop passes through a ``condition``
  step. A loop with no condition can never exit; the Marketplace only caught
  that at run time with its step limit.

References to things in the database (agents, tools, knowledge bases) are
checked separately by ``builder.services.references``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from builder.graph.condition_rules import MAX_INSTRUCTIONS, MODES, normalize_condition_config, rule_problem
from builder.graph.output_config import config_problem
from builder.graph.schema import TRIGGER_TYPES, WorkflowEdge, WorkflowNode, parse_tool_id


@dataclass(frozen=True)
class GraphProblem:
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    # Set for "connect this server first" problems, so a client can offer Connect.
    server_id: str | None = None

    def as_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        for key in ("node_id", "edge_id", "server_id"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def _name(node: WorkflowNode) -> str:
    return f"'{node.label or node.id}'"


def _condition_problems(node: WorkflowNode, out_edges: list[WorkflowEdge]) -> list[GraphProblem]:
    problems: list[GraphProblem] = []
    if not out_edges:
        problems.append(GraphProblem("condition_no_branches", f"Condition step {_name(node)} has no outgoing lines to choose from.", node.id))
    raw = node.condition_config
    if raw is None:
        return problems
    mode = raw.get("mode")
    if mode is not None and mode not in MODES:
        problems.append(GraphProblem("condition_config", f'Condition step {_name(node)}: mode must be "ai" or "rule".', node.id))
    instructions = raw.get("instructions")
    if instructions is not None and (not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS):
        problems.append(GraphProblem("condition_config", f"Condition step {_name(node)}: instructions must be text of at most {MAX_INSTRUCTIONS} characters.", node.id))
    edge_dicts = [e.model_dump() for e in out_edges]
    targets = {e.target for e in out_edges}
    cfg = normalize_condition_config(raw, edge_dicts)
    if cfg["default_branch"] and cfg["default_branch"] not in targets:
        problems.append(GraphProblem("condition_config", f'Condition step {_name(node)}: the "if nothing matches" line must be one of its own outgoing lines.', node.id))
    rules = raw.get("rules")
    if rules is not None and not isinstance(rules, dict):
        problems.append(GraphProblem("condition_config", f"Condition step {_name(node)}: rules must be an object.", node.id))
    for target, rule in (rules or {}).items() if isinstance(rules, dict) else []:
        if target not in targets:
            continue  # a line removed on the canvas — its old rule is ignored
        problem = rule_problem(rule)
        if problem:
            problems.append(GraphProblem("condition_config", f"Condition step {_name(node)}: the rule for the line to '{target}' {problem}.", node.id))
    return problems


def _strongly_connected(node_ids: list[str], outgoing: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm, iterative (graphs can be deep enough to hit recursion limits)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in node_ids:
        if root in index:
            continue
        work = [(root, iter(outgoing.get(root, [])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(outgoing.get(child, []))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return components


def validate_graph(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> list[GraphProblem]:
    problems: list[GraphProblem] = []
    if not nodes:
        return problems

    by_id: dict[str, WorkflowNode] = {}
    for node, count in Counter(n.id for n in nodes).items():
        if count > 1:
            problems.append(GraphProblem("duplicate_node", f"Two steps share the id '{node}'.", node))
    for n in nodes:
        by_id.setdefault(n.id, n)
    for edge_id, count in Counter(e.id for e in edges).items():
        if count > 1:
            problems.append(GraphProblem("duplicate_edge", f"Two lines share the id '{edge_id}'.", edge_id=edge_id))

    outgoing: dict[str, list[WorkflowEdge]] = {}
    incoming: dict[str, list[WorkflowEdge]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    valid_edges: list[WorkflowEdge] = []
    for e in edges:
        if e.source not in by_id or e.target not in by_id:
            problems.append(GraphProblem("edge_missing_node", f"Line '{e.id}' connects to a step that doesn't exist.", edge_id=e.id))
            continue
        if e.source == e.target:
            problems.append(GraphProblem("self_loop", "A step can't connect to itself.", e.source, e.id))
            continue
        if (e.source, e.target) in seen_pairs:
            problems.append(GraphProblem("duplicate_line", "These two steps are connected twice.", e.source, e.id))
            continue
        seen_pairs.add((e.source, e.target))
        valid_edges.append(e)
        outgoing.setdefault(e.source, []).append(e)
        incoming.setdefault(e.target, []).append(e)

    # ── Trigger and reachability ──
    triggers = [n for n in by_id.values() if n.type in TRIGGER_TYPES]
    if not triggers:
        problems.append(GraphProblem("no_trigger", "Add a trigger to start the workflow: Input, Manual Trigger, or Schedule Trigger."))
    elif len(triggers) > 1:
        for t in triggers[1:]:
            problems.append(GraphProblem("multiple_triggers", "A workflow can have only one trigger.", t.id))
    if triggers:
        start = triggers[0]
        if incoming.get(start.id):
            problems.append(GraphProblem("trigger_has_input", "The trigger can't have an incoming line.", start.id))
        reached = {start.id}
        frontier = [start.id]
        while frontier:
            frontier = [e.target for nid in frontier for e in outgoing.get(nid, []) if e.target not in reached]
            reached.update(frontier)
        for nid in by_id:
            if nid not in reached and by_id[nid].type not in TRIGGER_TYPES:
                problems.append(GraphProblem("unreachable", f"Step {_name(by_id[nid])} isn't reachable from the trigger, so it can never run.", nid))

    # ── Per step ──
    for n in by_id.values():
        outs = outgoing.get(n.id, [])
        ins = incoming.get(n.id, [])
        if n.type == "agent" and not n.agent_id and n.draft_agent is None:
            problems.append(GraphProblem("agent_missing", f"Agent step {_name(n)} has no agent selected.", n.id))
        elif n.type == "tool":
            if not n.tool_id:
                problems.append(GraphProblem("tool_missing", f"Tool step {_name(n)} has no tool selected.", n.id))
            elif parse_tool_id(n.tool_id) is None:
                problems.append(GraphProblem("tool_invalid", f"Tool step {_name(n)} has an invalid tool reference.", n.id))
        elif n.type == "condition":
            problems.extend(_condition_problems(n, outs))
        elif n.type == "join":
            policy = n.join_policy
            if len(ins) < 2:
                problems.append(GraphProblem("join_inputs", f"Join step {_name(n)} needs at least 2 incoming lines (has {len(ins)}).", n.id))
            if policy is not None and policy.mode == "count" and policy.min_required is None:
                problems.append(GraphProblem("join_policy", f'Join step {_name(n)}: "count" needs how many branches to wait for.', n.id))
            if policy is not None and policy.min_required is not None and policy.min_required > len(ins):
                problems.append(GraphProblem("join_policy", f"Join step {_name(n)} waits for {policy.min_required} branches but only {len(ins)} lead into it.", n.id))
        elif n.type == "output":
            problem = config_problem(n.output_config)
            if problem:
                problems.append(GraphProblem("output_config", f"Output step {_name(n)}: {problem}.", n.id))
            if outs:
                problems.append(GraphProblem("output_has_next", f"Output step {_name(n)} ends the workflow; it can't lead to another step.", n.id))
        elif n.type == "input" and n.variables:
            for name, count in Counter(v.name for v in n.variables).items():
                if count > 1:
                    problems.append(GraphProblem("input_variables", f"Input variable '{name}' is defined twice.", n.id))

    # ── Loops must be able to exit ──
    targets = {nid: [e.target for e in outgoing.get(nid, [])] for nid in by_id}
    for component in _strongly_connected(list(by_id), targets):
        if len(component) < 2:
            continue
        if not any(by_id[nid].type == "condition" for nid in component):
            first = sorted(component)[0]
            problems.append(GraphProblem(
                "loop_without_exit",
                "These steps form a loop with no condition step to leave it, so it would run forever: "
                + ", ".join(_name(by_id[nid]) for nid in sorted(component)) + ".",
                first,
            ))
    return problems


__all__ = ["GraphProblem", "validate_graph"]
