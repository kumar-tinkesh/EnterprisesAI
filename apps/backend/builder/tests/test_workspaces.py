"""Workspace isolation: what is made in one workspace of a tenant is not seen,
opened, run or listed from another — for the same person and for a colleague."""
from __future__ import annotations

from src.api.deps import CurrentUser

from builder.models import BuilderApproval, BuilderConversation, BuilderRun
from builder.tests.test_runs import demo, gateway, get_run, make_agent, reply, runtime, start, worker  # noqa: F401 — fixtures

B = "/api/v1/builder"
KB = "/api/v1/knowledge-bases"


def _user(tenant, workspace_id, uid="tu_1", role="tenant_user") -> CurrentUser:
    return CurrentUser(id=uid, email=f"{uid}@x.io", full_name=uid, role=role, tenant_id=tenant.id, workspace_id=workspace_id)


async def test_agents_workflows_knowledge_and_runs_stay_in_their_workspace(
    db, tenant, make_user_client, demo, gateway, runtime
):
    in_a = await make_user_client(_user(tenant, "ws_a"))
    in_b = await make_user_client(_user(tenant, "ws_b"))
    admin_b = await make_user_client(_user(tenant, "ws_b", uid="ta_1", role="tenant_admin"))

    agent = await make_agent(in_a, demo, ["echo"])
    wf = (await in_a.post(f"{B}/workflows", json={"name": "Flow", "nodes": [], "edges": []})).json()
    kb = (await in_a.post(KB, json={"name": "Handbook"})).json()
    assert {agent.get("id"), wf.get("id"), kb.get("id")} - {None} and len({agent["id"], wf["id"], kb["id"]}) == 3

    # Seen in A …
    assert [a["id"] for a in (await in_a.get(f"{B}/agents")).json()] == [agent["id"]]
    assert [w["id"] for w in (await in_a.get(f"{B}/workflows")).json()] == [wf["id"]]
    assert [k["id"] for k in (await in_a.get(KB)).json()] == [kb["id"]]

    # … not in B, not even for a tenant admin, and not by id.
    for client in (in_b, admin_b):
        assert (await client.get(f"{B}/agents")).json() == []
        assert (await client.get(f"{B}/workflows")).json() == []
        assert (await client.get(KB)).json() == []
        assert (await client.get(f"{B}/agents/{agent['id']}")).status_code == 404
        assert (await client.get(f"{B}/workflows/{wf['id']}")).status_code == 404
        assert (await client.get(f"{KB}/{kb['id']}")).status_code == 404
        assert (await client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "x"})).status_code == 404

    # An agent in B can't use A's knowledge base.
    r = await in_b.post(f"{B}/agents", json={"name": "B", "role": "r", "goal": "g", "config": {"knowledge_base_ids": [kb["id"]]}})
    assert r.status_code == 422, r.text

    # A run (and its chat) belongs to A: listed there, not in B.
    gateway([reply("Done.")])
    r = await in_a.post(f"{B}/agents/{agent['id']}/runs", json={"input": "hi", "new_conversation": True})
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    await worker(runtime).drain()
    assert (await get_run(in_a, run_id))["status"] == "succeeded"
    assert [x["id"] for x in (await in_a.get(f"{B}/runs")).json()] == [run_id]
    assert (await in_b.get(f"{B}/runs")).json() == []
    assert (await in_b.get(f"{B}/conversations")).json() == []
    conv = (await in_a.get(f"{B}/conversations")).json()
    run = await db.get(BuilderRun, run_id)
    assert run.workspace_id == "ws_a"
    assert len(conv) == 1 and (await db.get(BuilderConversation, conv[0]["id"])).workspace_id == "ws_a"

    # The dashboard overview counts only this workspace's things.
    over_a = (await in_a.get(f"{B}/overview")).json()
    over_b = (await in_b.get(f"{B}/overview")).json()
    assert len(over_a["items"]) == 2 and over_b["items"] == []


async def test_approvals_follow_the_run_into_its_workspace(db, tenant, make_user_client):
    in_a = await make_user_client(_user(tenant, "ws_a"))
    in_b = await make_user_client(_user(tenant, "ws_b"))
    db.add(BuilderRun(id="run_a", tenant_id=tenant.id, workspace_id="ws_a", owner_id="tu_1", kind="agent",
                      definition_version=1, definition={}, input={}, status="waiting", state={}))
    await db.flush()
    from builder.scope import run_workspace

    db.add(BuilderApproval(run_id="run_a", tenant_id=tenant.id, workspace_id=run_workspace("run_a"), owner_id="tu_1",
                           kind="tool_call", payload={}, status="pending"))
    await db.commit()
    [approval] = (await db.execute(__import__("sqlalchemy").select(BuilderApproval))).scalars().all()
    assert approval.workspace_id == "ws_a"
    assert len((await in_a.get(f"{B}/approvals")).json()) == 1
    assert (await in_b.get(f"{B}/approvals")).json() == []
