"""Which workflow steps run, and when — a pure state machine (no I/O).

The whole schedule lives in one JSON-able dict that the engine saves after
every step, so a resumed run continues exactly where it stopped.

Edges are ``unresolved`` -> ``fired`` (the source finished and this line was
taken), ``dead`` (a condition took another line, or the source was skipped)
or ``failed`` (the source failed but its failure is tolerated by a join).

A step becomes ready once every *forward* line into it is resolved:
* some fired          -> it runs, with the fired sources' outputs as input;
* none fired, none failed -> it is pruned (a branch not taken), and its own
  lines go dead in turn — so a step after a condition only waits for the
  branch that was actually taken;
* a join also sees which inputs failed, and its policy decides.

Loops. Lines are split into forward and back edges by a depth-first walk
from the trigger. A back edge firing (a condition sending work back for
another pass) starts a new round: every step reachable from its target is
reset, and the target runs again with the condition's text. Validation
already guarantees each loop has a condition to leave it; ``max_steps``
caps the rounds.

Node statuses: waiting, ready, running, paused (waiting on a person),
done, failed (tolerated), pruned.
"""
from __future__ import annotations

from dataclasses import dataclass

from builder.graph.schema import TRIGGER_TYPES
from builder.workflows.text import render_accumulated

WAITING, READY, RUNNING, PAUSED, DONE, FAILED, PRUNED = "waiting", "ready", "running", "paused", "done", "failed", "pruned"
FIRED, DEAD, EDGE_FAILED, UNRESOLVED = "fired", "dead", "failed", "unresolved"


@dataclass(frozen=True)
class Graph:
    nodes: dict[str, dict]
    edges: dict[str, dict]
    out_edges: dict[str, list[str]]
    forward_in: dict[str, list[str]]
    back_edges: frozenset[str]
    forward_out: dict[str, list[str]]
    trigger: str

    def label(self, node_id: str) -> str:
        node = self.nodes[node_id]
        return node.get("label") or node_id

    def reachable_forward(self, start: str) -> list[str]:
        seen, stack = [start], [start]
        while stack:
            for edge_id in self.forward_out.get(stack.pop(), []):
                target = self.edges[edge_id]["target"]
                if target not in seen:
                    seen.append(target)
                    stack.append(target)
        return seen


def build_graph(nodes: list[dict], edges: list[dict]) -> Graph:
    by_id = {n["id"]: n for n in nodes}
    trigger = next(n["id"] for n in nodes if n["type"] in TRIGGER_TYPES)
    edge_map = {e["id"]: e for e in edges if e["source"] in by_id and e["target"] in by_id}
    out: dict[str, list[str]] = {nid: [] for nid in by_id}
    for edge_id, e in edge_map.items():
        out[e["source"]].append(edge_id)

    # Back edges: a line to a step still on the current depth-first path.
    back: set[str] = set()
    state: dict[str, int] = {}  # 1 = on path, 2 = finished
    stack = [(trigger, iter(out[trigger]))]
    state[trigger] = 1
    while stack:
        node_id, it = stack[-1]
        advanced = False
        for edge_id in it:
            target = edge_map[edge_id]["target"]
            if state.get(target) == 1:
                back.add(edge_id)
            elif target not in state:
                state[target] = 1
                stack.append((target, iter(out[target])))
                advanced = True
                break
        if not advanced:
            state[node_id] = 2
            stack.pop()

    forward_in: dict[str, list[str]] = {nid: [] for nid in by_id}
    forward_out: dict[str, list[str]] = {nid: [] for nid in by_id}
    for edge_id, e in edge_map.items():
        if edge_id not in back:
            forward_in[e["target"]].append(edge_id)
            forward_out[e["source"]].append(edge_id)
    return Graph(by_id, edge_map, out, forward_in, frozenset(back), forward_out, trigger)


# ── State ────────────────────────────────────────────────────────────────────


def init_state(graph: Graph, input_text: str) -> dict:
    state = {
        "input": input_text,
        "nodes": {nid: {"status": WAITING, "attempt": 0, "tries": 0, "output": None, "error": None, "parts": []} for nid in graph.nodes},
        "edges": {edge_id: UNRESOLVED for edge_id in graph.edges},
        "failed_inputs": {},
        "steps": 0,
        "active_seconds": 0.0,
        "final": None,
        "sources": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    activate(state, graph.trigger, [("input", input_text)], input_text=input_text)
    return state


def activate(state: dict, node_id: str, parts: list[tuple[str, str]], *, input_text: str, retry: bool = False) -> None:
    """Make a step ready to run with these inputs (a new attempt)."""
    node = state["nodes"][node_id]
    node["status"] = READY
    node["attempt"] += 1
    node["tries"] = node["tries"] + 1 if retry else 1
    node["parts"] = [list(p) for p in parts]
    node["input"] = render_accumulated(parts, input_text)
    node["output"] = node["error"] = None


def ready(state: dict) -> list[str]:
    return [nid for nid, n in state["nodes"].items() if n["status"] == READY]


def running(state: dict) -> list[str]:
    return [nid for nid, n in state["nodes"].items() if n["status"] == RUNNING]


def paused(state: dict) -> list[str]:
    return [nid for nid, n in state["nodes"].items() if n["status"] == PAUSED]


def resume_interrupted(state: dict) -> None:
    """A step that was running (the worker died) or paused (a decision came
    in) runs again — the same attempt, so its checkpoints and tool-call
    records are picked up rather than redone."""
    for node in state["nodes"].values():
        if node["status"] in (RUNNING, PAUSED):
            node["status"] = READY


def _evaluate(state: dict, graph: Graph, node_id: str) -> None:
    node = state["nodes"][node_id]
    if node["status"] != WAITING:
        return
    incoming = graph.forward_in[node_id]
    if any(state["edges"][e] == UNRESOLVED for e in incoming):
        return
    fired = [graph.edges[e]["source"] for e in incoming if state["edges"][e] == FIRED]
    failed = [graph.edges[e]["source"] for e in incoming if state["edges"][e] == EDGE_FAILED]
    if not fired and not failed:
        prune(state, graph, node_id)
        return
    state["failed_inputs"][node_id] = failed
    parts = [(graph.label(src), state["nodes"][src]["output"] or "") for src in fired]
    activate(state, node_id, parts, input_text=state["input"])


def _resolve_out(state: dict, graph: Graph, node_id: str, edge_status: dict[str, str]) -> None:
    loops: list[tuple[str, str]] = []
    for edge_id in graph.out_edges[node_id]:
        state["edges"][edge_id] = edge_status[edge_id]
        if edge_id in graph.back_edges and edge_status[edge_id] == FIRED:
            loops.append((edge_id, graph.edges[edge_id]["target"]))
    for edge_id in graph.forward_out[node_id]:
        _evaluate(state, graph, graph.edges[edge_id]["target"])
    for _edge_id, target in loops:
        _start_round(state, graph, target, node_id)


def _start_round(state: dict, graph: Graph, target: str, from_node: str) -> None:
    # Read before the reset: the step sending work back is usually inside the loop itself.
    carried = state["nodes"][from_node]["output"] or ""
    region = graph.reachable_forward(target)
    region_set = set(region)
    for nid in region:
        node = state["nodes"][nid]
        if node["status"] in (DONE, FAILED, PRUNED, WAITING):
            node["status"], node["output"], node["error"] = WAITING, None, None
    for edge_id, e in graph.edges.items():
        if edge_id not in graph.back_edges and e["source"] in region_set and e["target"] in region_set:
            state["edges"][edge_id] = UNRESOLVED
    activate(state, target, [(graph.label(from_node), carried)], input_text=state["input"])


def complete(state: dict, graph: Graph, node_id: str, output: str, *, take: set[str] | None = None) -> None:
    """A step finished. ``take`` (conditions only): which targets to go on to."""
    node = state["nodes"][node_id]
    if node["status"] != RUNNING:
        return  # stale: a loop round reset it while it ran
    node["status"], node["output"] = DONE, output
    status = {
        edge_id: (FIRED if take is None or graph.edges[edge_id]["target"] in take else DEAD)
        for edge_id in graph.out_edges[node_id]
    }
    _resolve_out(state, graph, node_id, status)


def fail_tolerated(state: dict, graph: Graph, node_id: str, error: str) -> None:
    """A failure the graph can absorb (every line out goes to a join that
    doesn't need every branch): record it and let the joins decide."""
    node = state["nodes"][node_id]
    node["status"], node["error"] = FAILED, error
    _resolve_out(state, graph, node_id, {e: EDGE_FAILED for e in graph.out_edges[node_id]})


def prune(state: dict, graph: Graph, node_id: str) -> None:
    state["nodes"][node_id]["status"] = PRUNED
    _resolve_out(state, graph, node_id, {e: DEAD for e in graph.out_edges[node_id]})


def retry(state: dict, node_id: str) -> None:
    node = state["nodes"][node_id]
    activate(state, node_id, [tuple(p) for p in node["parts"]], input_text=state["input"], retry=True)


def tolerant(graph: Graph, node_id: str) -> bool:
    """True if every line out of this step feeds a join that can go on without it."""
    outs = graph.out_edges[node_id]
    if not outs:
        return False
    for edge_id in outs:
        target = graph.nodes[graph.edges[edge_id]["target"]]
        if target["type"] != "join" or (target.get("join_policy") or {}).get("mode", "all") == "all":
            return False
    return True


def sinks_done(state: dict, graph: Graph) -> list[tuple[str, str]]:
    """Finished steps with nothing after them — the answer when there's no output step."""
    return [
        (graph.label(nid), state["nodes"][nid]["output"] or "")
        for nid in graph.nodes
        if state["nodes"][nid]["status"] == DONE and not graph.forward_out[nid] and graph.nodes[nid]["type"] not in TRIGGER_TYPES
    ]


__all__ = [
    "Graph", "build_graph", "init_state", "activate", "ready", "running", "paused", "resume_interrupted",
    "complete", "fail_tolerated", "prune", "retry", "tolerant", "sinks_done",
    "WAITING", "READY", "RUNNING", "PAUSED", "DONE", "FAILED", "PRUNED",
]
