"""REST endpoint tests for the User domain API (read-only MCP catalog).

Covers the access-filtered ``/catalog`` route across roles (vendor_admin,
solo_user, tenant_user). Server creation/grants here are only setup —
performed via the ``admin_client`` fixture against the vendor domain's
routes — the assertions are all about what each caller's catalog view
contains.
"""
from __future__ import annotations

import pytest

BASE = "/api/v1/vendor/resources"


def _mcp_payload(name="finance.getInvoice", is_global=False):
    return {
        "name": name,
        "description": "Retrieve a vendor invoice via MCP.",
        "source_url": "https://mcp.example.com/invoice",
        "is_global": is_global,
    }


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
