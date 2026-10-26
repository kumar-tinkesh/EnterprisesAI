"""Agents & workflows API: CRUD, sharing rules, reference checks, preflight."""
from __future__ import annotations

import pytest_asyncio

from src.api.deps import CurrentUser
from src.core.roles import Roles
from src.models import Tenant

from knowledge.models import KnowledgeBase
from vendor.models import MCPTool, TenantResourceGrant, VendorMCPServer
from vendor.services import mcp_auth

AGENTS = "/api/v1/builder/agents"
WORKFLOWS = "/api/v1/builder/workflows"


@pytest_asyncio.fixture
async def catalog(db, tenant):
    """A global server with two tools, a private (ungranted) one, and a knowledge base."""
    mail = VendorMCPServer(name="Mail", is_global=True, transport="streamable_http", server_url="https://mail.example/mcp", auth_config={})
    private = VendorMCPServer(name="Private", is_global=False, transport="streamable_http", server_url="https://p.example/mcp", auth_config={})
    db.add_all([mail, private])
    await db.flush()
    db.add_all([
        MCPTool(mcp_server_id=mail.id, name="send_email", description="Send an email"),
        MCPTool(mcp_server_id=mail.id, name="list_emails", description="List emails"),
        MCPTool(mcp_server_id=private.id, name="secret", description="x"),
    ])
    kb = KnowledgeBase(tenant_id=tenant.id, owner_id="tu_1", name="Policies")
    db.add(kb)
    await db.commit()
    return {"mail": mail, "private": private, "kb": kb}


def agent_body(**overrides) -> dict:
    body = {"name": "Mailer", "role": "Assistant", "goal": "Handle email", "config": {}}
    body.update(overrides)
    return body


def graph(agent_id: str | None = None, tool_id: str | None = None) -> dict:
    nodes = [{"id": "in", "type": "input"}]
    edges = []
    last = "in"
    if agent_id:
        nodes.append({"id": "a", "type": "agent", "agent_id": agent_id})
        edges.append({"id": "e1", "source": last, "target": "a"})
        last = "a"
    if tool_id:
        nodes.append({"id": "t", "type": "tool", "tool_id": tool_id})
        edges.append({"id": "e2", "source": last, "target": "t"})
        last = "t"
    nodes.append({"id": "out", "type": "output"})
    edges.append({"id": "e3", "source": last, "target": "out"})
    return {"nodes": nodes, "edges": edges}


def tid(server, tool: str) -> str:
    return f"mcp:{server.id}:{tool}"


# ── Agents ───────────────────────────────────────────────────────────────────


async def test_agent_crud_and_config_defaults(tenant_client, catalog):
    body = agent_body(config={"tool_ids": [tid(catalog["mail"], "send_email")], "knowledge_base_ids": [catalog["kb"].id], "llm": {"temperature": 0.2}})
    r = await tenant_client.post(AGENTS, json=body)
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["version"] == 1 and agent["can_manage"] is True
    assert agent["config"]["tools"]["max_calls"] == 8  # defaults filled in
    assert agent["config"]["approvals"] == {"read": False, "edit": True, "delete": True}

    r = await tenant_client.patch(f"{AGENTS}/{agent['id']}", json={"goal": "Answer email", "expected_version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = await tenant_client.patch(f"{AGENTS}/{agent['id']}", json={"goal": "stale edit", "expected_version": 1})
    assert r.status_code == 409

    assert [a["id"] for a in (await tenant_client.get(AGENTS)).json()] == [agent["id"]]
    assert (await tenant_client.delete(f"{AGENTS}/{agent['id']}")).status_code == 204
    assert (await tenant_client.get(f"{AGENTS}/{agent['id']}")).status_code == 404


async def test_agent_config_is_validated(tenant_client, catalog):
    r = await tenant_client.post(AGENTS, json=agent_body(config={"llm": {"temprature": 0.5}}))
    assert r.status_code == 422  # misspelled key
    r = await tenant_client.post(AGENTS, json=agent_body(config={"tools": {"max_calls": 99}}))
    assert r.status_code == 422  # out of range
    r = await tenant_client.post(AGENTS, json=agent_body(config={"tool_ids": ["send_email"]}))
    assert r.status_code == 422  # not a tool reference


async def test_agent_references_are_checked(tenant_client, catalog):
    cases = {
        "server_unavailable": tid(catalog["private"], "secret"),
        "tool_unavailable": tid(catalog["mail"], "delete_everything"),
    }
    for code, tool in cases.items():
        r = await tenant_client.post(AGENTS, json=agent_body(config={"tool_ids": [tool]}))
        assert r.status_code == 422 and r.json()["problems"][0]["code"] == code, (code, r.text)
    r = await tenant_client.post(AGENTS, json=agent_body(config={"knowledge_base_ids": ["no-such-kb"]}))
    assert r.json()["problems"][0]["code"] == "knowledge_base_missing"


async def test_granted_private_server_becomes_usable(db, tenant_client, tenant, catalog):
    db.add(TenantResourceGrant(tenant_id=tenant.id, resource_type="mcp", resource_id=catalog["private"].id))
    await db.commit()
    r = await tenant_client.post(AGENTS, json=agent_body(config={"tool_ids": [tid(catalog["private"], "secret")]}))
    assert r.status_code == 201, r.text


async def test_sharing_rules(tenant_client, make_user_client, tenant, catalog):
    agent = (await tenant_client.post(AGENTS, json=agent_body())).json()
    colleague = await make_user_client(CurrentUser(id="tu_2", email="c@x.io", full_name="C", role=Roles.TENANT_USER, tenant_id=tenant.id))
    admin = await make_user_client(CurrentUser(id="ta_1", email="a@x.io", full_name="A", role=Roles.TENANT_ADMIN, tenant_id=tenant.id))

    seen = (await colleague.get(f"{AGENTS}/{agent['id']}")).json()
    assert seen["can_manage"] is False
    assert (await colleague.patch(f"{AGENTS}/{agent['id']}", json={"name": "x"})).status_code == 403
    assert (await colleague.delete(f"{AGENTS}/{agent['id']}")).status_code == 403
    assert (await admin.patch(f"{AGENTS}/{agent['id']}", json={"name": "Renamed"})).json()["name"] == "Renamed"


async def test_other_tenants_and_vendor_admins_are_kept_out(db, tenant_client, make_user_client, admin_client, catalog):
    agent = (await tenant_client.post(AGENTS, json=agent_body())).json()
    wf = (await tenant_client.post(WORKFLOWS, json={"name": "Flow", **graph()})).json()
    db.add(Tenant(id="tenant_2", name="Other", slug="other", status="active"))
    await db.commit()
    outsider = await make_user_client(CurrentUser(id="o_1", email="o@x.io", full_name="O", role=Roles.TENANT_ADMIN, tenant_id="tenant_2"))
    assert (await outsider.get(AGENTS)).json() == []
    assert (await outsider.get(f"{AGENTS}/{agent['id']}")).status_code == 404
    assert (await outsider.get(WORKFLOWS)).json() == []
    assert (await outsider.delete(f"{WORKFLOWS}/{wf['id']}")).status_code == 404
    assert (await admin_client.get(AGENTS)).status_code == 403


# ── Workflows ────────────────────────────────────────────────────────────────


async def test_workflow_crud_with_its_own_agents(tenant_client, catalog):
    wf = (await tenant_client.post(WORKFLOWS, json={"name": "Inbox triage"})).json()
    assert wf["version"] == 1 and wf["nodes"] == []

    own = (await tenant_client.post(AGENTS, json=agent_body(name="Triage", workflow_id=wf["id"]))).json()
    standalone = (await tenant_client.post(AGENTS, json=agent_body(name="Standalone"))).json()
    assert [a["id"] for a in (await tenant_client.get(AGENTS)).json()] == [standalone["id"]]
    assert [a["id"] for a in (await tenant_client.get(AGENTS, params={"workflow_id": wf["id"]})).json()] == [own["id"]]

    r = await tenant_client.patch(f"{WORKFLOWS}/{wf['id']}", json={**graph(own["id"], tid(catalog["mail"], "send_email")), "expected_version": 1})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 2 and saved["node_count"] == 4
    assert [a["id"] for a in saved["agents"]] == [own["id"]]
    assert "data" not in saved["nodes"][0]

    # An agent a workflow step uses can't be deleted out from under it.
    assert (await tenant_client.delete(f"{AGENTS}/{own['id']}")).status_code == 409

    # Deleting the workflow takes its own agents with it, not standalone ones.
    assert (await tenant_client.delete(f"{WORKFLOWS}/{wf['id']}")).status_code == 204
    assert (await tenant_client.get(f"{AGENTS}/{own['id']}")).status_code == 404
    assert (await tenant_client.get(f"{AGENTS}/{standalone['id']}")).status_code == 200


async def test_workflow_save_refuses_problems_and_lists_them_all(tenant_client, catalog):
    other_wf = (await tenant_client.post(WORKFLOWS, json={"name": "Other"})).json()
    foreign = (await tenant_client.post(AGENTS, json=agent_body(workflow_id=other_wf["id"]))).json()
    body = {
        "name": "Broken",
        "nodes": [
            {"id": "in", "type": "input"},
            {"id": "a", "type": "agent", "agent_id": foreign["id"]},
            {"id": "t", "type": "tool", "tool_id": tid(catalog["mail"], "nope")},
            {"id": "lost", "type": "agent", "agent_id": "missing-agent"},
        ],
        "edges": [{"id": "e1", "source": "in", "target": "a"}, {"id": "e2", "source": "a", "target": "t"}],
    }
    r = await tenant_client.post(WORKFLOWS, json=body)
    assert r.status_code == 422
    got = {p["code"] for p in r.json()["problems"]}
    assert {"agent_of_other_workflow", "tool_unavailable", "unreachable", "agent_not_found"} <= got
    assert (await tenant_client.get(WORKFLOWS)).json()[0]["name"] == "Other"  # nothing saved

    # The same check without saving, for the canvas.
    r = await tenant_client.post(f"{WORKFLOWS}/validate", json=body)
    assert r.status_code == 200 and r.json()["ok"] is False and len(r.json()["problems"]) >= 4


async def test_step_overrides_are_validated(tenant_client, catalog):
    agent = (await tenant_client.post(AGENTS, json=agent_body())).json()
    body = {"name": "F", **graph(agent["id"])}
    body["nodes"][1]["config_overrides"] = {"tools": {"max_calls": 500}}
    r = await tenant_client.post(WORKFLOWS, json=body)
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "agent_overrides"


async def test_preflight_is_per_user(tenant_client, tenant_user, db, catalog):
    agent = (await tenant_client.post(AGENTS, json=agent_body(config={"tool_ids": [tid(catalog["mail"], "list_emails")]}))).json()
    wf = (await tenant_client.post(WORKFLOWS, json={"name": "F", **graph(agent["id"], tid(catalog["mail"], "send_email"))})).json()

    r = (await tenant_client.post(f"{WORKFLOWS}/{wf['id']}/preflight")).json()
    assert r["ok"] is False
    # One missing connection used by two steps is one problem, with the server to connect.
    assert [(p["code"], p["server_id"]) for p in r["problems"]] == [("not_connected", catalog["mail"].id)]
    assert (await tenant_client.get(f"{AGENTS}/{agent['id']}/preflight")).json()["ok"] is False

    await mcp_auth.store_server_credentials(db, server_id=catalog["mail"].id, credentials={}, tenant_id=tenant_user.tenant_id, user_id=tenant_user.id)
    await db.commit()
    assert (await tenant_client.post(f"{WORKFLOWS}/{wf['id']}/preflight")).json() == {"ok": True, "problems": []}
    assert (await tenant_client.get(f"{AGENTS}/{agent['id']}/preflight")).json()["ok"] is True


async def test_preflight_catches_things_deleted_after_saving(tenant_client, db, catalog):
    kb = KnowledgeBase(tenant_id="tenant_test_01", owner_id="tu_1", name="Temp")
    db.add(kb)
    await db.commit()
    agent = (await tenant_client.post(AGENTS, json=agent_body(config={"knowledge_base_ids": [kb.id]}))).json()
    wf = (await tenant_client.post(WORKFLOWS, json={"name": "F", **graph(agent["id"])})).json()
    await db.delete(kb)
    await db.commit()
    problems = (await tenant_client.post(f"{WORKFLOWS}/{wf['id']}/preflight")).json()["problems"]
    assert [p["code"] for p in problems] == ["knowledge_base_missing"]
