"""The admin Apps page: per-server counts, a server's tools with what they can do, grants and taking one back."""
from __future__ import annotations

import pytest

from vendor.models import MCPTool
from vendor.services import mcp_auth

BASE = "/api/v1/vendor/resources"


async def test_overview_and_details(admin_client, tenant_client, db, tenant):
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "notes", "description": "", "source_url": "https://mcp.example.com/notes", "is_global": False})
    assert res.status_code == 201, res.text
    sid = res.json()["id"]
    db.add_all([
        MCPTool(mcp_server_id=sid, name="list_notes", description="List notes"),
        MCPTool(mcp_server_id=sid, name="delete_note", description="Delete a note"),
    ])
    await mcp_auth.store_server_credentials(db, server_id=sid, credentials={"API_KEY": "admin"}, tenant_id=None)
    await mcp_auth.store_server_credentials(db, server_id=sid, credentials={"API_KEY": "mine"}, tenant_id=tenant.id, user_id="tu_1")
    await db.commit()
    assert (await admin_client.post(f"{BASE}/grants", json={"tenant_id": tenant.id, "resource_type": "mcp", "resource_id": sid})).status_code == 201

    [row] = [r for r in (await admin_client.get(f"{BASE}/mcp/overview")).json() if r["id"] == sid]
    # The admin's own test credential isn't a person's connection.
    assert (row["users_connected"], row["tools"], row["tenants_granted"]) == (1, 2, 1)

    d = (await admin_client.get(f"{BASE}/mcp/{sid}/details")).json()
    assert d["users_connected"] == 1 and d["grants"] == [{"tenant_id": tenant.id, "name": "Test Tenant"}]
    assert {t["name"]: t["risk"] for t in d["tools"]} == {"delete_note": "delete", "list_notes": "read"}
    assert "admin" not in str(d) and "mine" not in str(d)

    assert (await tenant_client.get(f"{BASE}/mcp/overview")).status_code == 403
    assert (await admin_client.delete(f"{BASE}/mcp/{sid}/grants/{tenant.id}")).status_code == 204
    assert (await admin_client.get(f"{BASE}/mcp/{sid}/details")).json()["grants"] == []
    assert (await admin_client.delete(f"{BASE}/mcp/{sid}/grants/{tenant.id}")).status_code == 404
    assert (await admin_client.get(f"{BASE}/mcp/nope/details")).status_code == 404


async def test_a_tool_turned_off_is_kept_from_agents(admin_client, db):
    from builder.agents.tools import resolve_agent_tools
    from builder.services.tool_runtime import ToolNotFound
    from builder.services.tool_runtime.invoke import resolve_tool
    from src.api.deps import CurrentUser

    res = await admin_client.post(f"{BASE}/mcp", json={"name": "insta", "description": "", "source_url": "https://mcp.example.com/i", "is_global": True})
    sid = res.json()["id"]
    db.add_all([MCPTool(mcp_server_id=sid, name="whoami"), MCPTool(mcp_server_id=sid, name="unofficial_inbox")])
    await db.commit()

    r = await admin_client.put(f"{BASE}/mcp/{sid}/disabled-tools", json={"names": ["unofficial_inbox", " "]})
    assert r.status_code == 200 and r.json() == {"names": ["unofficial_inbox"]}
    tools = {t["name"]: t["on"] for t in (await admin_client.get(f"{BASE}/mcp/{sid}/details")).json()["tools"]}
    assert tools == {"unofficial_inbox": False, "whoami": True}

    db.expire_all()
    got = await resolve_agent_tools(db, [f"mcp:{sid}:whoami", f"mcp:{sid}:unofficial_inbox"])
    assert [t.tool_name for t in got] == ["whoami"]
    user = CurrentUser(id="va_1", email="va@x.io", full_name="A", role="vendor_admin", tenant_id=None)
    with pytest.raises(ToolNotFound, match="turned off"):
        await resolve_tool(db, user=user, server_id=sid, tool_name="unofficial_inbox")

    assert (await admin_client.put(f"{BASE}/mcp/{sid}/disabled-tools", json={"names": []})).json() == {"names": []}
