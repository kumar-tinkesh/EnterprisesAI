"""Tests for the LangGraph executor + tool invocation."""
from __future__ import annotations

import pytest

from vendor_resources.schemas import (
    AgentEdge,
    AgentNode,
    CompiledAgentSpec,
    CreateVendorToolRequest,
)
from vendor_resources.services.executor import _topo_order, execute_spec
from vendor_resources.services.tool_executor import invoke_tool
from vendor_resources.services.tool_service import create_tool


async def _make_tool(db, name: str, *, endpoint_url: str | None = None, method: str = "GET"):
    tool = await create_tool(
        db,
        data=CreateVendorToolRequest(
            name=name,
            description=f"desc {name}",
            category="finance",
            method=method,
            endpoint_url=endpoint_url,
            parameters_schema={"type": "object"},
            is_global=True,
        ),
        actor_id="va_1",
    )
    await db.commit()
    await db.refresh(tool)
    return tool


def _spec(nodes, edges=None):
    return CompiledAgentSpec(agent_name="t", description="d", nodes=nodes, edges=edges or [])


# ── topo ordering ────────────────────────────────────────────────────────────


def test_topo_order_respects_edges():
    n1, n2, n3 = AgentNode(id="n1"), AgentNode(id="n2"), AgentNode(id="n3")
    # n1 -> n2 -> n3  (declared in reverse to prove topo works)
    order = _topo_order([n3, n2, n1], [AgentEdge(source="n1", target="n2"), AgentEdge(source="n2", target="n3")])
    assert order == ["n1", "n2", "n3"]


def test_topo_order_cycle_falls_back_to_declaration():
    n1, n2 = AgentNode(id="n1"), AgentNode(id="n2")
    order = _topo_order([n1, n2], [AgentEdge(source="n1", target="n2"), AgentEdge(source="n2", target="n1")])
    assert order == ["n1", "n2"]  # declaration order


def test_topo_order_no_edges_is_declaration():
    ns = [AgentNode(id="a"), AgentNode(id="b")]
    assert _topo_order(ns, []) == ["a", "b"]


# ── execute_spec (simulated, endpoint-less tools) ────────────────────────────


@pytest.mark.asyncio
async def test_execute_spec_simulated_for_endpointless_tools(db):
    t1 = await _make_tool(db, "finance.getInvoice")
    t2 = await _make_tool(db, "hr.lookupEmployee")
    spec = _spec(
        [AgentNode(id="n1", tool_id=t1.id), AgentNode(id="n2", tool_id=t2.id)],
        [AgentEdge(source="n1", target="n2")],
    )
    out = await execute_spec(db, spec)
    assert set(out["results"].keys()) == {"n1", "n2"}
    assert out["results"]["n1"]["simulated"] is True
    assert [t["node"] for t in out["trace"]] == ["n1", "n2"]


@pytest.mark.asyncio
async def test_execute_spec_topo_order_reversed_by_edge(db):
    t1 = await _make_tool(db, "finance.first")
    t2 = await _make_tool(db, "finance.second")
    spec = _spec(
        [AgentNode(id="n1", tool_id=t1.id), AgentNode(id="n2", tool_id=t2.id)],
        [AgentEdge(source="n2", target="n1")],  # n2 before n1
    )
    out = await execute_spec(db, spec)
    assert [t["node"] for t in out["trace"]] == ["n2", "n1"]


@pytest.mark.asyncio
async def test_execute_spec_cycle_falls_back(db):
    t1 = await _make_tool(db, "finance.a")
    t2 = await _make_tool(db, "finance.b")
    spec = _spec(
        [AgentNode(id="n1", tool_id=t1.id), AgentNode(id="n2", tool_id=t2.id)],
        [AgentEdge(source="n1", target="n2"), AgentEdge(source="n2", target="n1")],
    )
    out = await execute_spec(db, spec)  # must not deadlock
    assert set(out["results"].keys()) == {"n1", "n2"}


@pytest.mark.asyncio
async def test_execute_spec_empty(db):
    out = await execute_spec(db, _spec([]))
    assert out == {"results": {}, "trace": []}


@pytest.mark.asyncio
async def test_execute_spec_unconfigured_node_simulated(db):
    spec = _spec([AgentNode(id="n1", tool_id=None, unconfigured=True)])
    out = await execute_spec(db, spec)
    assert out["results"]["n1"]["simulated"] is True


# ── invoke_tool: real httpx call (mocked) ────────────────────────────────────


class _FakeResp:
    def __init__(self, status, body_json, text):
        self.status_code = status
        self._json = body_json
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, json=None):
        self.last = (method, url, json)
        return _FakeResp(200, {"ok": True, "echo": json}, '{"ok": true}')


@pytest.mark.asyncio
async def test_invoke_tool_real_endpoint(db, monkeypatch):
    from vendor_resources.services import tool_executor

    tool = await _make_tool(db, "finance.real", endpoint_url="https://example.com/api/invoice", method="POST")
    monkeypatch.setattr(tool_executor.httpx, "AsyncClient", _FakeAsyncClient)

    node = AgentNode(id="n1", tool_id=tool.id, args={"invoice_id": "INV-1"})
    result = await invoke_tool(db, node, {})
    assert result["simulated"] is False
    assert result["status"] == 200
    assert result["body"]["ok"] is True
    assert result["body"]["echo"] == {"invoice_id": "INV-1"}


@pytest.mark.asyncio
async def test_invoke_tool_missing_tool_simulated(db):
    node = AgentNode(id="n1", tool_id="does-not-exist")
    result = await invoke_tool(db, node, {})
    assert result["simulated"] is True
    assert "not found" in result["message"]