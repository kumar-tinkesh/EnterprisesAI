"""REST endpoint tests for the Vendor Resources API (Phase 1).

Covers: tool creation/listing, RBAC (admin vs non-admin), the access-filtered
catalog across roles, tenant grants (create + idempotent), and tool deletion
with grant cascade.
"""
from __future__ import annotations

import pytest

BASE = "/api/v1/vendor/resources"


def _tool_payload(name="finance.getInvoice", is_global=False, category="finance", endpoint_url="https://api.example.com/invoices"):
    return {
        "name": name,
        "description": "Retrieve a vendor invoice.",
        "category": category,
        "method": "GET",
        "endpoint_url": endpoint_url,
        "parameters_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"],
        },
        "is_global": is_global,
    }


# ── health ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(admin_client):
    res = await admin_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "backend"


# ── tool creation + RBAC ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tool_as_vendor_admin(admin_client):
    res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.alpha", is_global=True))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "tool.alpha"
    assert body["is_global"] is True
    assert body["vault_secret_ref"] is None
    assert "id" in body and len(body["id"]) == 36


@pytest.mark.asyncio
async def test_create_tool_as_solo_user_forbidden(solo_client):
    res = await solo_client.post(f"{BASE}/tools", json=_tool_payload("tool.beta"))
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_tool_validation_error(admin_client):
    res = await admin_client.post(f"{BASE}/tools", json={"name": "x", "description": "d"})
    assert res.status_code == 422


# ── list tools (admin) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools_admin_sees_created(admin_client):
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.listed.1", is_global=True))
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.listed.2", is_global=False))
    res = await admin_client.get(f"{BASE}/tools")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()}
    assert {"tool.listed.1", "tool.listed.2"}.issubset(names)


@pytest.mark.asyncio
async def test_list_tools_as_solo_user_forbidden(solo_client):
    res = await solo_client.get(f"{BASE}/tools")
    assert res.status_code == 403


# ── catalog access-filtering ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_solo_sees_only_global(admin_client, solo_client):
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("glob.solo", is_global=True))
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("priv.solo", is_global=False))
    res = await solo_client.get(f"{BASE}/catalog")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["tools"]}
    assert "glob.solo" in names
    assert "priv.solo" not in names
    assert res.json()["count"] == len(res.json()["tools"])


@pytest.mark.asyncio
async def test_catalog_tenant_sees_granted_plus_global(admin_client, tenant_client):
    # one global + one private (to be granted to the tenant)
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("glob.tenant", is_global=True))
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("priv.tenant", is_global=False))
    private_id = create_res.json()["id"]

    grant_res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": "tenant_test_01", "resource_type": "vendor_tool", "resource_id": private_id},
    )
    assert grant_res.status_code == 201

    res = await tenant_client.get(f"{BASE}/catalog")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["tools"]}
    assert "glob.tenant" in names
    assert "priv.tenant" in names  # inherited via grant


@pytest.mark.asyncio
async def test_catalog_tenant_does_not_see_ungranted_private(admin_client, tenant_client):
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("priv.ungranted", is_global=False))
    res = await tenant_client.get(f"{BASE}/catalog")
    names = {t["name"] for t in res.json()["tools"]}
    assert "priv.ungranted" not in names


# ── catalog semantic ranking (q param) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_q_ranks_relevant_tool_first(admin_client, mock_gateway):
    inv = await admin_client.post(f"{BASE}/tools", json=_tool_payload("finance.getInvoice", is_global=True))
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("hr.lookupEmployee", is_global=True))
    res = await admin_client.get(f"{BASE}/catalog", params={"q": "show me invoices"})
    assert res.status_code == 200
    tools = res.json()["tools"]
    assert tools, "expected at least one tool"
    assert tools[0]["id"] == inv.json()["id"]


@pytest.mark.asyncio
async def test_catalog_q_respects_access_control(admin_client, solo_client, mock_gateway):
    # non-global invoice tool NOT granted to anyone → solo user must not see it
    private = await admin_client.post(
        f"{BASE}/tools", json=_tool_payload("finance.privateInvoice", is_global=False)
    )
    res = await solo_client.get(f"{BASE}/catalog", params={"q": "invoice"})
    ids = {t["id"] for t in res.json()["tools"]}
    assert private.json()["id"] not in ids


@pytest.mark.asyncio
async def test_catalog_q_top_k_truncation(admin_client, mock_gateway):
    for i in range(6):
        await admin_client.post(f"{BASE}/tools", json=_tool_payload(f"finance.invoice{i}", is_global=True))
    res = await admin_client.get(f"{BASE}/catalog", params={"q": "invoice", "top_k": 3})
    assert len(res.json()["tools"]) <= 3


@pytest.mark.asyncio
async def test_catalog_q_without_embeddings_falls_back(admin_client):
    # no mock_gateway → no embeddings; q still returns the access-filtered list
    await admin_client.post(f"{BASE}/tools", json=_tool_payload("fallback.glob", is_global=True))
    res = await admin_client.get(f"{BASE}/catalog", params={"q": "anything"})
    assert res.status_code == 200
    assert any(t["name"] == "fallback.glob" for t in res.json()["tools"])


# ── embed endpoint ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embed_endpoint_returns_204(admin_client, mock_gateway):
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.embed.target", is_global=True))
    res = await admin_client.post(f"{BASE}/tools/{create_res.json()['id']}/embed")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_embed_endpoint_missing_tool_404(admin_client):
    res = await admin_client.post(f"{BASE}/tools/nonexistent-id/embed")
    assert res.status_code == 404


# ── AI Compiler endpoints ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agents_compile_returns_spec(admin_client, mock_llm):
    create_res = await admin_client.post(
        f"{BASE}/tools", json=_tool_payload("finance.getInvoice", is_global=True)
    )
    tool_id = create_res.json()["id"]
    res = await admin_client.post(
        f"{BASE}/agents/compile", json={"query": "show me invoices", "top_k": 5}
    )
    assert res.status_code == 200, res.text
    spec = res.json()
    assert spec["agent_name"]
    assert len(spec["nodes"]) >= 1
    assert spec["nodes"][0]["tool_id"] == tool_id


@pytest.mark.asyncio
async def test_agents_run_returns_spec_and_results(admin_client, mock_llm):
    create_res = await admin_client.post(
        f"{BASE}/tools", json=_tool_payload("finance.getInvoice", is_global=True, endpoint_url=None)
    )
    tool_id = create_res.json()["id"]
    res = await admin_client.post(
        f"{BASE}/agents/run", json={"query": "show me invoices", "top_k": 5}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spec"]["nodes"][0]["tool_id"] == tool_id
    # endpoint-less tool → simulated result
    node_id = body["spec"]["nodes"][0]["id"]
    assert node_id in body["results"]
    assert body["results"][node_id]["simulated"] is True
    assert len(body["trace"]) >= 1


@pytest.mark.asyncio
async def test_agents_compile_unauthenticated_401(anon_client):
    res = await anon_client.post(f"{BASE}/agents/compile", json={"query": "x"})
    assert res.status_code == 401


# ── grants ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_resource_creates_grant(admin_client, tenant):
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.grant.target", is_global=False))
    tool_id = create_res.json()["id"]

    res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": tenant.id, "resource_type": "vendor_tool", "resource_id": tool_id},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["tenant_id"] == tenant.id
    assert body["resource_id"] == tool_id


@pytest.mark.asyncio
async def test_grant_resource_idempotent_returns_200(admin_client, tenant):
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.grant.idem", is_global=False))
    tool_id = create_res.json()["id"]
    payload = {"tenant_id": tenant.id, "resource_type": "vendor_tool", "resource_id": tool_id}

    first = await admin_client.post(f"{BASE}/grants", json=payload)
    second = await admin_client.post(f"{BASE}/grants", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_grant_resource_missing_tenant_404(admin_client):
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.grant.notenant", is_global=False))
    res = await admin_client.post(
        f"{BASE}/grants",
        json={
            "tenant_id": "nonexistent-tenant",
            "resource_type": "vendor_tool",
            "resource_id": create_res.json()["id"],
        },
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_grant_resource_missing_tool_404(admin_client, tenant):
    res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": tenant.id, "resource_type": "vendor_tool", "resource_id": "nonexistent-tool"},
    )
    assert res.status_code == 404


# ── delete + cascade ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_tool_cascades_grants(admin_client, tenant_client, tenant):
    create_res = await admin_client.post(f"{BASE}/tools", json=_tool_payload("tool.delete.cascade", is_global=False))
    tool_id = create_res.json()["id"]
    await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": tenant.id, "resource_type": "vendor_tool", "resource_id": tool_id},
    )
    # tenant can see it via the grant
    cat = await tenant_client.get(f"{BASE}/catalog")
    assert "tool.delete.cascade" in {t["name"] for t in cat.json()["tools"]}

    del_res = await admin_client.delete(f"{BASE}/{tool_id}")
    assert del_res.status_code == 204

    # tenant can no longer see it
    cat2 = await tenant_client.get(f"{BASE}/catalog")
    assert "tool.delete.cascade" not in {t["name"] for t in cat2.json()["tools"]}


@pytest.mark.asyncio
async def test_delete_tool_not_found(admin_client):
    res = await admin_client.delete(f"{BASE}/nonexistent-tool-id")
    assert res.status_code == 404