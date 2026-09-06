"""REST endpoint tests for the Vendor domain API (MCP server lifecycle).

Covers: MCP server creation/listing, RBAC (admin vs non-admin), tenant
grants (create + idempotent), MCP server deletion with grant cascade, and
repo analysis. Catalog access-filtering tests (the ``user`` domain's
``/catalog`` route) live in ``user/tests/test_router.py`` instead — grants
and server creation here are only setup for those.
"""
from __future__ import annotations

import pytest

BASE = "/api/v1/vendor/resources"


def _mcp_payload(name="finance.getInvoice", is_global=False):
    """New format: AddMCPServerRequest with source_url."""
    return {
        "name": name,
        "description": "Retrieve a vendor invoice via MCP.",
        "source_url": "https://mcp.example.com/invoice",
        "is_global": is_global,
    }


def _analyze_repo_payload(repo_url="https://github.com/org/mcp-server"):
    return {"repo_url": repo_url}


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
    assert body["status"] == "UNCONNECTED"
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


# ── MCP repo analysis ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_repo_as_vendor_admin(admin_client):
    """Vendor admin can analyze a GitHub repository for MCP characteristics."""
    res = await admin_client.post(
        f"{BASE}/mcp/analyze-repo",
        json=_analyze_repo_payload("https://github.com/modelcontextprotocol/servers"),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "detected" in body
    assert "transport" in body
    assert "runtime" in body
    assert "suggested_command" in body
    assert "remote_endpoint" in body
    assert "required_env_vars" in body
    assert "auth_type" in body
    assert "hints" in body


@pytest.mark.asyncio
async def test_analyze_repo_as_solo_user_forbidden(solo_client):
    """Solo users cannot access the analyze-repo endpoint."""
    res = await solo_client.post(
        f"{BASE}/mcp/analyze-repo",
        json=_analyze_repo_payload("https://github.com/org/repo"),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_analyze_repo_validation_error(admin_client):
    """Missing repo_url should return validation error."""
    res = await admin_client.post(f"{BASE}/mcp/analyze-repo", json={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_analyze_repo_invalid_url(admin_client):
    """Invalid URL should return error."""
    res = await admin_client.post(
        f"{BASE}/mcp/analyze-repo",
        json=_analyze_repo_payload("not-a-valid-url"),
    )
    # Should handle gracefully - may return 200 with error info or 400
    assert res.status_code in (200, 400)


@pytest.mark.asyncio
async def test_disconnect_mcp_server(admin_client):
    """Disconnecting an MCP server should reset status to UNCONNECTED."""
    created = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("mcp.disc"))
    assert created.status_code == 201
    server_id = created.json()["id"]

    res = await admin_client.post(f"{BASE}/mcp/{server_id}/disconnect")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UNCONNECTED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
