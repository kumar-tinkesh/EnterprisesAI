"""Tests for the AI Compiler (schema shrinking + LLM spec generation)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from src.api.deps import CurrentUser
from src.core.roles import Roles

from vendor_resources.models import VendorTool
from vendor_resources.schemas import CreateVendorToolRequest
from vendor_resources.services.compiler import compile_agent, shrink_schema
from vendor_resources.services.tool_service import create_tool


def _user(role: str, tenant_id: str | None = None) -> CurrentUser:
    return CurrentUser(id=f"u_{role}", email=f"{role}@x.io", full_name=role, role=role, tenant_id=tenant_id)


async def _make_tool(db, name: str, is_global: bool, description: str = "desc") -> VendorTool:
    tool = await create_tool(
        db,
        data=CreateVendorToolRequest(
            name=name,
            description=description,
            category="finance",
            method="GET",
            parameters_schema={
                "type": "object",
                "description": "Invoice lookup",
                "properties": {
                    "invoice_id": {"type": "string", "description": "The invoice identifier"},
                },
                "required": ["invoice_id"],
            },
            is_global=is_global,
        ),
        actor_id="va_1",
    )
    await db.commit()
    await db.refresh(tool)
    return tool


# ── schema shrinking ─────────────────────────────────────────────────────────


def test_shrink_schema_drops_verbose_keys():
    schema = {
        "type": "object",
        "description": "top",  # dropped
        "properties": {
            "invoice_id": {"type": "string", "description": "the id"},  # dropped
        },
        "required": ["invoice_id"],
    }
    out = shrink_schema(schema)
    assert "description" not in out
    assert "description" not in out["properties"]["invoice_id"]
    # structure preserved
    assert out["type"] == "object"
    assert out["properties"]["invoice_id"]["type"] == "string"
    assert out["required"] == ["invoice_id"]


def test_shrink_schema_non_dict_passthrough():
    assert shrink_schema([]) == []
    assert shrink_schema("x") == "x"


# ── compile_agent ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_agent_returns_valid_spec_with_bound_tool(db, mock_llm):
    tool = await _make_tool(db, "finance.getInvoice", is_global=True, description="Retrieve a vendor invoice")
    spec = await compile_agent(db, user=_user(Roles.SOLO_USER), query="show me invoices", top_k=5)
    assert spec.agent_name
    assert len(spec.nodes) == 1
    assert spec.nodes[0].tool_id == tool.id
    assert mock_llm.complete_calls >= 1


@pytest.mark.asyncio
async def test_compile_agent_solo_user_never_binds_private_tool(db, mock_llm):
    # only a non-global tool exists → solo user's authorized catalog is empty
    await _make_tool(db, "finance.privateInvoice", is_global=False)
    spec = await compile_agent(db, user=_user(Roles.SOLO_USER), query="invoice", top_k=5)
    bound = [n.tool_id for n in spec.nodes if n.tool_id is not None]
    assert bound == []  # nothing authorized to bind


@pytest.mark.asyncio
async def test_compile_agent_empty_catalog_returns_empty_spec(db, mock_llm):
    spec = await compile_agent(db, user=_user(Roles.SOLO_USER), query="anything", top_k=5)
    assert spec.nodes == []


@pytest.mark.asyncio
async def test_compile_agent_neutralises_disallowed_tool_id(db, monkeypatch):
    """Defense-in-depth: an LLM-emitted tool_id not in the authorized set is neutralised."""
    from vendor_resources.services import embeddings
    from apps.llm_gateway.types import CompletionResponse

    # one authorized global tool
    await _make_tool(db, "finance.getInvoice", is_global=True)

    class _Rogue:
        async def embed(self, texts, **_kw):
            from apps.llm_gateway.types import EmbeddingResponse
            return EmbeddingResponse(embeddings=[[1.0]], model="m", provider="p", usage=None)

        async def complete(self, request, **_kw):
            rogue = {
                "agent_name": "rogue",
                "description": "x",
                "nodes": [{"id": "n1", "node_type": "tool.call", "tool_id": "not-an-authorized-id", "args": {}}],
                "edges": [],
            }
            return CompletionResponse(content=json.dumps(rogue), model="m", provider="p")

        async def close(self):
            pass

    monkeypatch.setattr(embeddings, "get_gateway", lambda: _Rogue())
    spec = await compile_agent(db, user=_user(Roles.SOLO_USER), query="invoice", top_k=5)
    node = spec.nodes[0]
    assert node.tool_id is None
    assert node.unconfigured is True


@pytest.mark.asyncio
async def test_compile_agent_bad_json_falls_back(db, monkeypatch):
    from vendor_resources.services import embeddings
    from apps.llm_gateway.types import CompletionResponse

    await _make_tool(db, "finance.getInvoice", is_global=True)

    class _Bad:
        async def embed(self, texts, **_kw):
            from apps.llm_gateway.types import EmbeddingResponse
            return EmbeddingResponse(embeddings=[[1.0]], model="m", provider="p", usage=None)

        async def complete(self, request, **_kw):
            return CompletionResponse(content="this is not json", model="m", provider="p")

        async def close(self):
            pass

    monkeypatch.setattr(embeddings, "get_gateway", lambda: _Bad())
    spec = await compile_agent(db, user=_user(Roles.SOLO_USER), query="invoice", top_k=5)
    # retried then fell back to the linear fallback spec
    assert spec.agent_name == "fallback_agent"
    assert len(spec.nodes) == 1
    assert spec.nodes[0].tool_id is not None  # bound to the top candidate