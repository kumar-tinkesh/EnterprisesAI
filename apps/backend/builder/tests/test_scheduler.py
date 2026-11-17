"""The workflow schedule (builder.workflows.scheduler) — pure state, no I/O."""
from __future__ import annotations

from builder.workflows import scheduler as S


def g(nodes: list[tuple[str, str]], edges: list[tuple[str, str]], **node_extra):
    node_dicts = [{"id": i, "type": t, **node_extra.get(i, {})} for i, t in nodes]
    edge_dicts = [{"id": f"{a}->{b}", "source": a, "target": b} for a, b in edges]
    return S.build_graph(node_dicts, edge_dicts)


def run_to(state, node_id, output="", take=None):
    """Start and finish one step (what the engine does)."""
    assert state["nodes"][node_id]["status"] == S.READY, (node_id, state["nodes"][node_id]["status"])
    state["nodes"][node_id]["status"] = S.RUNNING
    S.complete(state, GRAPH, node_id, output, take=take)


def statuses(state):
    return {nid: n["status"] for nid, n in state["nodes"].items()}


def test_linear_flow_passes_text_along():
    global GRAPH
    GRAPH = g([("in", "input"), ("a", "agent"), ("out", "output")], [("in", "a"), ("a", "out")])
    st = S.init_state(GRAPH, "hello")
    assert S.ready(st) == ["in"]
    run_to(st, "in", "hello")
    assert S.ready(st) == ["a"] and st["nodes"]["a"]["input"] == "hello"
    run_to(st, "a", "answer")
    assert st["nodes"]["out"]["parts"] == [["a", "answer"]]


def test_parallel_branches_wait_for_each_other():
    global GRAPH
    GRAPH = g(
        [("in", "input"), ("x", "agent"), ("y", "agent"), ("j", "join"), ("out", "output")],
        [("in", "x"), ("in", "y"), ("x", "j"), ("y", "j"), ("j", "out")],
    )
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    assert sorted(S.ready(st)) == ["x", "y"]  # both at once
    run_to(st, "x", "X")
    assert "j" not in S.ready(st)  # still waiting for y
    run_to(st, "y", "Y")
    assert S.ready(st) == ["j"]
    assert st["nodes"]["j"]["input"] == "--- x ---\nX\n\n--- y ---\nY"


def test_condition_prunes_the_branch_not_taken():
    global GRAPH
    GRAPH = g(
        [("in", "input"), ("c", "condition"), ("big", "agent"), ("small", "agent"), ("after_small", "agent"), ("out", "output")],
        [("in", "c"), ("c", "big"), ("c", "small"), ("small", "after_small"), ("big", "out"), ("after_small", "out")],
    )
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    run_to(st, "c", "q", take={"big"})
    s = statuses(st)
    assert s["small"] == S.PRUNED and s["after_small"] == S.PRUNED  # pruning travels down the branch
    assert S.ready(st) == ["big"]
    run_to(st, "big", "B")
    assert S.ready(st) == ["out"] and st["nodes"]["out"]["parts"] == [["big", "B"]]


def test_review_loop_starts_a_new_round():
    global GRAPH
    GRAPH = g(
        [("in", "input"), ("w", "agent"), ("c", "condition"), ("out", "output")],
        [("in", "w"), ("w", "c"), ("c", "w"), ("c", "out")],
    )
    assert GRAPH.back_edges == {"c->w"}
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    run_to(st, "w", "draft 1")
    run_to(st, "c", "draft 1", take={"w"})  # needs edits
    assert S.ready(st) == ["w"]
    assert st["nodes"]["w"]["attempt"] == 2 and st["nodes"]["w"]["input"] == "draft 1"
    assert st["nodes"]["out"]["status"] == S.WAITING  # reset for the new round, not pruned
    run_to(st, "w", "draft 2")
    run_to(st, "c", "draft 2", take={"out"})  # approved
    assert S.ready(st) == ["out"] and st["nodes"]["out"]["parts"] == [["c", "draft 2"]]


def test_tolerated_failure_reaches_a_lenient_join():
    global GRAPH
    GRAPH = g(
        [("in", "input"), ("x", "tool"), ("y", "agent"), ("j", "join")],
        [("in", "x"), ("in", "y"), ("x", "j"), ("y", "j")],
        j={"join_policy": {"mode": "any"}},
    )
    assert S.tolerant(GRAPH, "x") and not S.tolerant(GRAPH, "in")
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    st["nodes"]["x"]["status"] = S.RUNNING
    S.fail_tolerated(st, GRAPH, "x", "boom")
    run_to(st, "y", "Y")
    assert S.ready(st) == ["j"]
    assert st["failed_inputs"]["j"] == ["x"] and st["nodes"]["j"]["parts"] == [["y", "Y"]]


def test_retry_keeps_the_inputs_and_counts_tries():
    global GRAPH
    GRAPH = g([("in", "input"), ("a", "agent")], [("in", "a")])
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    st["nodes"]["a"]["status"] = S.RUNNING
    S.retry(st, "a")
    a = st["nodes"]["a"]
    assert (a["status"], a["attempt"], a["tries"], a["input"]) == (S.READY, 2, 2, "q")


def test_interrupted_steps_resume_under_the_same_attempt():
    global GRAPH
    GRAPH = g([("in", "input"), ("a", "agent"), ("b", "human_approval")], [("in", "a"), ("in", "b")])
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    st["nodes"]["a"]["status"] = S.RUNNING
    st["nodes"]["b"]["status"] = S.PAUSED
    S.resume_interrupted(st)
    assert sorted(S.ready(st)) == ["a", "b"]
    assert st["nodes"]["a"]["attempt"] == 1 and st["nodes"]["b"]["attempt"] == 1


def test_stale_completion_after_a_reset_is_ignored():
    global GRAPH
    GRAPH = g([("in", "input"), ("a", "agent")], [("in", "a")])
    st = S.init_state(GRAPH, "q")
    run_to(st, "in", "q")
    S.complete(st, GRAPH, "a", "late")  # never marked running in this round
    assert st["nodes"]["a"]["status"] == S.READY and st["nodes"]["a"]["output"] is None
