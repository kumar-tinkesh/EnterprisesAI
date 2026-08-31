"""LangGraph executor for a :class:`CompiledAgentSpec`.

Turns the compiled DAG into a ``langgraph`` :class:`StateGraph` and runs it.
Nodes are executed in **topological order** derived from the spec's edges
(falling back to declaration order if the edges are absent or cyclic), wired as
a linear chain ``START → n0 → n1 → … → END``. Each node invokes its bound
Vendor Tool via :func:`tool_executor.invoke_tool` (real ``httpx`` call or
simulated result for endpoint-less tools) and accumulates the result into the
graph state.

Conditional / parallel branching is accepted on the spec (the ``condition``
field is preserved) but not yet wired into the graph — linear-in-topo-order is
robust and always terminates. Branching is a future enhancement.

State channels use reducers so ``results``/``trace`` accumulate correctly even
if langgraph fans out internally.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from vendor_resources.schemas import AgentEdge, AgentNode, CompiledAgentSpec
from vendor_resources.services.tool_executor import invoke_tool

logger = logging.getLogger("vendor_resources.executor")


def _merge_dict(prev: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    return {**(prev or {}), **(new or {})}


def _merge_list(prev: list[Any] | None, new: list[Any] | None) -> list[Any]:
    return (prev or []) + (new or [])


class AgentState(TypedDict):
    query: str
    results: Annotated[dict[str, Any], _merge_dict]
    trace: Annotated[list[dict[str, Any]], _merge_list]


def _topo_order(nodes: list[AgentNode], edges: list[AgentEdge]) -> list[str]:
    """Return node ids in topological order; falls back to declaration order.

    Uses Kahn's algorithm. On a cycle, missing nodes, or any anomaly, returns
    the declaration order so execution never deadlocks.
    """
    ids = [n.id for n in nodes]
    if not ids:
        return []
    id_set = set(ids)
    # adjacency + in-degree, ignoring edges that reference unknown nodes
    adj: dict[str, list[str]] = {nid: [] for nid in ids}
    indeg: dict[str, int] = {nid: 0 for nid in ids}
    for e in edges:
        if e.source in id_set and e.target in id_set and e.source != e.target:
            adj[e.source].append(e.target)
            indeg[e.target] += 1

    queue = [nid for nid in ids if indeg[nid] == 0]
    order: list[str] = []
    # preserve declaration order among equal-priority nodes
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(ids) or set(order) != id_set:
        # cycle or disconnected → safe fallback
        logger.warning("executor: spec edges form an invalid DAG; using declaration order")
        return ids
    return order


def _make_node_callable(db: AsyncSession, node: AgentNode):
    async def _fn(state: AgentState) -> dict[str, Any]:
        result = await invoke_tool(db, node, state)
        return {
            "results": {node.id: result},
            "trace": [{"node": node.id, "node_type": node.node_type, "result": result}],
        }

    return _fn


async def execute_spec(db: AsyncSession, spec: CompiledAgentSpec) -> dict[str, Any]:
    """Execute a compiled spec via LangGraph; returns ``{results, trace}``.

    ``results`` maps node id → tool result dict; ``trace`` is the ordered list
    of node executions.
    """
    if not spec.nodes:
        return {"results": {}, "trace": []}

    order = _topo_order(spec.nodes, spec.edges)
    by_id = {n.id: n for n in spec.nodes}

    graph = StateGraph(AgentState)
    for nid in order:
        graph.add_node(nid, _make_node_callable(db, by_id[nid]))

    # Linear chain in topological order: START → n0 → n1 → … → n_last → END.
    graph.add_edge(START, order[0])
    for a, b in zip(order, order[1:]):
        graph.add_edge(a, b)
    graph.add_edge(order[-1], END)

    app = graph.compile()
    final = await app.ainvoke({"query": "", "results": {}, "trace": []})
    return {
        "results": dict(final.get("results", {})),
        "trace": list(final.get("trace", [])),
    }


__all__ = ["execute_spec", "AgentState"]