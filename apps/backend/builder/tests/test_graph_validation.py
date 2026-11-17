"""Structural workflow validation (builder.graph.validation) — pure, no DB."""
from __future__ import annotations

from builder.graph.schema import WorkflowEdge, WorkflowNode
from builder.graph.validation import validate_graph

TOOL = "mcp:srv-1:send_email"


def n(node_id: str, type_: str, **kw) -> WorkflowNode:
    return WorkflowNode(id=node_id, type=type_, **kw)


def e(source: str, target: str, edge_id: str | None = None, **kw) -> WorkflowEdge:
    return WorkflowEdge(id=edge_id or f"{source}->{target}", source=source, target=target, **kw)


def codes(nodes, edges) -> list[str]:
    return [p.code for p in validate_graph(nodes, edges)]


def test_valid_graph_with_branches_join_and_output():
    nodes = [
        n("in", "input", variables=[{"name": "email", "type": "text", "required": True}]),
        n("a", "agent", agent_id="agent-1"),
        n("t", "tool", tool_id=TOOL),
        n("j", "join", join_policy={"mode": "all"}),
        n("out", "output", output_config={"format": "markdown"}),
    ]
    edges = [e("in", "a"), e("in", "t"), e("a", "j"), e("t", "j"), e("j", "out")]
    assert validate_graph(nodes, edges) == []


def test_empty_graph_is_a_valid_draft():
    assert validate_graph([], []) == []


def test_trigger_rules():
    assert codes([n("a", "agent", agent_id="x")], []) == ["no_trigger"]
    assert "multiple_triggers" in codes([n("i", "input"), n("m", "manual_trigger")], [])
    assert "trigger_has_input" in codes(
        [n("i", "input"), n("c", "condition")], [e("i", "c", condition="go"), e("c", "i", condition="back")]
    )


def test_unreachable_step():
    problems = validate_graph([n("i", "input"), n("a", "agent", agent_id="x")], [])
    assert [(p.code, p.node_id) for p in problems] == [("unreachable", "a")]


def test_edge_problems():
    got = codes(
        [n("i", "input"), n("a", "agent", agent_id="x")],
        [e("i", "a"), e("i", "a", "dup"), e("a", "a"), e("i", "ghost")],
    )
    assert {"duplicate_line", "self_loop", "edge_missing_node"} <= set(got)


def test_step_fields():
    got = codes(
        [n("i", "input"), n("a", "agent"), n("t", "tool"), n("t2", "tool", tool_id="slack.send")],
        [e("i", "a"), e("i", "t"), e("i", "t2")],
    )
    assert got.count("agent_missing") == 1
    assert got.count("tool_missing") == 1
    assert got.count("tool_invalid") == 1


def test_join_rules():
    one_input = codes([n("i", "input"), n("j", "join")], [e("i", "j")])
    assert one_input == ["join_inputs"]
    nodes = [n("i", "input"), n("a", "agent", agent_id="x"), n("b", "agent", agent_id="y"), n("j", "join", join_policy={"mode": "count"})]
    edges = [e("i", "a"), e("i", "b"), e("a", "j"), e("b", "j")]
    assert codes(nodes, edges) == ["join_policy"]
    nodes[-1] = n("j", "join", join_policy={"mode": "count", "min_required": 3})
    assert codes(nodes, edges) == ["join_policy"]


def test_condition_rules():
    assert codes([n("i", "input"), n("c", "condition")], [e("i", "c")]) == ["condition_no_branches"]
    nodes = [
        n("i", "input"),
        n("c", "condition", condition_config={"mode": "rule", "rules": {"a": {"op": "gt", "value": "lots"}}, "default_branch": "nowhere"}),
        n("a", "agent", agent_id="x"),
    ]
    got = codes(nodes, [e("i", "c"), e("c", "a", condition="big")])
    assert got.count("condition_config") == 2  # numeric rule without a number + foreign default branch


def test_output_rules():
    nodes = [n("i", "input"), n("o", "output", output_config={"format": "pdf"}), n("a", "agent", agent_id="x")]
    got = codes(nodes, [e("i", "o"), e("o", "a")])
    assert {"output_config", "output_has_next"} <= set(got)


def test_duplicate_input_variables():
    node = n("i", "input", variables=[{"name": "x"}, {"name": "x"}])
    assert codes([node], []) == ["input_variables"]


def test_loops_need_a_condition_to_exit():
    nodes = [n("i", "input"), n("a", "agent", agent_id="x"), n("b", "agent", agent_id="y")]
    problems = validate_graph(nodes, [e("i", "a"), e("a", "b"), e("b", "a")])
    assert [p.code for p in problems] == ["loop_without_exit"]

    # A review loop through a condition step is a real pattern and allowed.
    nodes = [n("i", "input"), n("w", "agent", agent_id="writer"), n("c", "condition"), n("o", "output")]
    edges = [e("i", "w"), e("w", "c"), e("c", "w", condition="Needs edits"), e("c", "o", condition="Approved")]
    assert validate_graph(nodes, edges) == []


def test_reports_every_problem_at_once():
    nodes = [n("a", "agent"), n("t", "tool"), n("j", "join")]
    got = codes(nodes, [e("a", "j")])
    assert {"no_trigger", "agent_missing", "tool_missing", "join_inputs"} <= set(got)


def test_canvas_only_fields_are_dropped():
    node = WorkflowNode.model_validate({"id": "i", "type": "input", "data": {"label": "x"}, "selected": True, "position": {"x": 1, "y": 2}})
    assert node.model_dump(exclude_none=True) == {"id": "i", "type": "input", "position": {"x": 1.0, "y": 2.0}}
