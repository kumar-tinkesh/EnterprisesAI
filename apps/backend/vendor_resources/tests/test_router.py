"""REST endpoint tests for the Vendor Resources API (MCP).

Covers: MCP server creation/listing, RBAC (admin vs non-admin),
the access-filtered catalog across roles, tenant grants (create +
idempotent), and MCP server deletion with grant cascade.
"""
from __future__ import annotations

import pytest

BASE = "/api/v1/vendor/resources"


def _mcp_payload(name="finance.getInvoice", is_global=False):
    return {
        "name": name,
        "description": "Retrieve a vendor invoice via MCP.",
        "transport": "sse",
        "server_url": "https://mcp.example.com/invoice",
        "bound_tools": ["getInvoice"],
        "is_global": is_global,
    }


# ── health ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(admin_client):
    res = await admin_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "backend"


# ── MCP creation + RBAC ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_mcp_as_vendor_admin(admin_client):
    res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.alpha", is_global=True))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "mcp.alpha"
    assert body["is_global"] is True
    assert "id" in body and len(body["id"]) == 36


@pytest.mark.asyncio
async def test_create_mcp_as_solo_user_forbidden(solo_client):
    res = await solo_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.beta"))
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_mcp_validation_error(admin_client):
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "x", "description": "d"})
    assert res.status_code == 422


# ── list MCP servers (admin) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_mcp_admin_sees_created(admin_client):
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.listed.1", is_global=True))
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.listed.2", is_global=False))
    res = await admin_client.get(f"{BASE}/mcp")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()}
    assert {"mcp.listed.1", "mcp.listed.2"}.issubset(names)


@pytest.mark.asyncio
async def test_list_mcp_as_solo_user_forbidden(solo_client):
    res = await solo_client.get(f"{BASE}/mcp")
    assert res.status_code == 403


# ── catalog access-filtering ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_solo_sees_only_global(admin_client, solo_client):
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("glob.solo", is_global=True))
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("priv.solo", is_global=False))
    res = await solo_client.get(f"{BASE}/catalog")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["servers"]}
    assert "glob.solo" in names
    assert "priv.solo" not in names
    assert res.json()["count"] == len(res.json()["servers"])


@pytest.mark.asyncio
async def test_catalog_tenant_sees_granted_plus_global(admin_client, tenant_client):
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("glob.tenant", is_global=True))
    create_res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("priv.tenant", is_global=False))
    private_id = create_res.json()["id"]

    grant_res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": "tenant_test_01", "resource_type": "mcp", "resource_id": private_id},
    )
    assert grant_res.status_code == 201

    res = await tenant_client.get(f"{BASE}/catalog")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["servers"]}
    assert "glob.tenant" in names
    assert "priv.tenant" in names


@pytest.mark.asyncio
async def test_catalog_tenant_does_not_see_ungranted_private(admin_client, tenant_client):
    await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("priv.ungranted", is_global=False))
    res = await tenant_client.get(f"{BASE}/catalog")
    names = {t["name"] for t in res.json()["servers"]}
    assert "priv.ungranted" not in names


# ── grants ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_resource_creates_grant(admin_client, tenant):
    create_res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.grant.target"))
    server_id = create_res.json()["id"]

    res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": tenant.id, "resource_type": "mcp", "resource_id": server_id},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["tenant_id"] == tenant.id
    assert body["resource_id"] == server_id


@pytest.mark.asyncio
async def test_grant_resource_idempotent_returns_200(admin_client, tenant):
    create_res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.grant.idem"))
    server_id = create_res.json()["id"]
    payload = {"tenant_id": tenant.id, "resource_type": "mcp", "resource_id": server_id}

    first = await admin_client.post(f"{BASE}/grants", json=payload)
    second = await admin_client.post(f"{BASE}/grants", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_grant_resource_missing_tenant_404(admin_client):
    create_res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.notenant"))
    res = await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": "nonexistent-tenant", "resource_type": "mcp", "resource_id": create_res.json()["id"]},
    )
    assert res.status_code == 404


# ── delete + cascade ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_mcp_cascades_grants(admin_client, tenant_client, tenant):
    create_res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.delete.cascade"))
    server_id = create_res.json()["id"]
    await admin_client.post(
        f"{BASE}/grants",
        json={"tenant_id": tenant.id, "resource_type": "mcp", "resource_id": server_id},
    )
    cat = await tenant_client.get(f"{BASE}/catalog")
    assert "mcp.delete.cascade" in {t["name"] for t in cat.json()["servers"]}

    del_res = await admin_client.delete(f"{BASE}/{server_id}")
    assert del_res.status_code == 204

    cat2 = await tenant_client.get(f"{BASE}/catalog")
    assert "mcp.delete.cascade" not in {t["name"] for t in cat2.json()["servers"]}


@pytest.mark.asyncio
async def test_delete_mcp_not_found(admin_client):
    res = await admin_client.delete(f"{BASE}/nonexistent-server-id")
    assert res.status_code == 404