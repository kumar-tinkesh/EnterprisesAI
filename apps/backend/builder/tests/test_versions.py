"""Version history: every save is recorded, says what changed, and can be restored."""
from __future__ import annotations

from sqlalchemy import delete, func, select

from builder.config import get_builder_settings
from builder.models import BuilderAgent, BuilderSchedule, BuilderVersion
from builder.tests.test_runs import demo, make_agent, runtime  # noqa: F401  (fixtures)
from builder.versions.service import summarize_agent, summarize_workflow

A = "/api/v1/builder/agents"
WF = "/api/v1/builder/workflows"


def _flow(writer: dict, *, schedule: dict | None = None, extra_step: bool = False) -> dict:
    trigger = {"id": "start", "type": "schedule_trigger" if schedule else "input", "position": {"x": 0, "y": 0}}
    if schedule:
        trigger["schedule"] = schedule
    nodes = [trigger, {"id": "w", "type": "agent", "draft_agent": writer, "position": {"x": 300, "y": 0}},
             {"id": "out", "type": "output", "position": {"x": 900, "y": 0}}]
    edges = [{"id": "e1", "source": "start", "target": "w"}, {"id": "e2", "source": "w", "target": "out"}]
    if extra_step:
        nodes.insert(2, {"id": "ok", "type": "human_approval", "label": "Check", "position": {"x": 600, "y": 0}})
        edges = [edges[0], {"id": "e2", "source": "w", "target": "ok"}, {"id": "e3", "source": "ok", "target": "out"}]
    return {"nodes": nodes, "edges": edges}


WRITER = {"name": "Writer", "role": "writer", "goal": "Write it", "instructions": "Be brief."}


# ── summaries ────────────────────────────────────────────────────────────────


def test_summaries_say_what_changed():
    old = {"name": "A", "goal": "g", "instructions": "i", "config": {"tool_ids": ["mcp:s:echo"]}}
    new = {"name": "A", "goal": "g2", "instructions": "i2", "config": {"tool_ids": ["mcp:s:send_note"]}}
    assert summarize_agent(old, new) == "Changed the goal and instructions; added send_note; removed echo"
    assert summarize_agent(old, old) == "No changes"

    base = {"name": "F", "nodes": [{"id": "a", "type": "input", "position": {"x": 0}}, {"id": "b", "type": "output"}], "edges": [], "config": {}}
    grown = {**base, "nodes": base["nodes"] + [{"id": "c", "type": "human_approval", "label": "Check"}], "config": {"max_steps": 9}}
    assert summarize_workflow(base, grown) == "Added Check; changed settings"
    moved = {**base, "nodes": [{"id": "a", "type": "input", "position": {"x": 50}}, {"id": "b", "type": "output"}]}
    assert summarize_workflow(base, moved) == "Rearranged the canvas"


# ── agents ───────────────────────────────────────────────────────────────────


async def test_agent_history_and_restore(tenant_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"])
    r = await tenant_client.patch(f"{A}/{agent['id']}", json={"goal": "Help a lot", "config": {"tool_ids": [f"mcp:{demo.id}:send_note"]}, "expected_version": 1})
    assert r.status_code == 200, r.text

    versions = (await tenant_client.get(f"{A}/{agent['id']}/versions")).json()
    assert [(v["version"], v["note"], v["is_current"]) for v in versions] == [(2, "Saved", True), (1, "Created", False)]
    assert versions[0]["summary"] == "Changed the goal; added send_note; removed echo"
    assert versions[0]["author_name"] == "Tenant User"
    v1 = (await tenant_client.get(f"{A}/{agent['id']}/versions/1")).json()
    assert v1["snapshot"]["goal"] == "Help" and v1["snapshot"]["config"]["tool_ids"] == [f"mcp:{demo.id}:echo"]

    assert (await tenant_client.post(f"{A}/{agent['id']}/versions/1/restore", json={"expected_version": 1})).status_code == 409
    r = await tenant_client.post(f"{A}/{agent['id']}/versions/1/restore", json={"expected_version": 2})
    assert r.status_code == 200, r.text
    assert (r.json()["version"], r.json()["goal"], r.json()["config"]["tool_ids"]) == (3, "Help", [f"mcp:{demo.id}:echo"])
    top = (await tenant_client.get(f"{A}/{agent['id']}/versions")).json()[0]
    assert (top["version"], top["note"], top["summary"]) == (3, "Restored from v1", "Changed the goal; added echo; removed send_note")


async def test_only_managers_restore_but_everyone_sees_history(tenant_client, make_user_client, demo, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, ["echo"])
    await tenant_client.patch(f"{A}/{agent['id']}", json={"goal": "Other"})
    colleague = await make_user_client(CurrentUser(id="tu_9", email="c@x.io", full_name="C", role="tenant_user", tenant_id=tenant.id))
    assert len((await colleague.get(f"{A}/{agent['id']}/versions")).json()) == 2
    assert (await colleague.post(f"{A}/{agent['id']}/versions/1/restore", json={})).status_code == 403
    assert (await tenant_client.get(f"{A}/{agent['id']}/versions/99")).status_code == 404


async def test_definitions_from_before_history_get_a_baseline(db, tenant_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"])
    await db.execute(delete(BuilderVersion))  # as if it was created before version history existed
    await db.commit()
    await tenant_client.patch(f"{A}/{agent['id']}", json={"goal": "New goal"})
    versions = (await tenant_client.get(f"{A}/{agent['id']}/versions")).json()
    assert [(v["version"], v["note"]) for v in versions] == [(2, "Saved"), (1, "Before version history")]
    r = await tenant_client.post(f"{A}/{agent['id']}/versions/1/restore", json={})
    assert r.json()["goal"] == "Help"


async def test_old_versions_are_pruned(db, tenant_client, demo, monkeypatch):
    monkeypatch.setattr(get_builder_settings(), "BUILDER_VERSIONS_KEEP", 3)
    agent = await make_agent(tenant_client, demo, ["echo"])
    for i in range(4):
        await tenant_client.patch(f"{A}/{agent['id']}", json={"goal": f"Goal {i}"})
    assert [v["version"] for v in (await tenant_client.get(f"{A}/{agent['id']}/versions")).json()] == [5, 4, 3]


# ── workflows ────────────────────────────────────────────────────────────────


async def test_workflow_restore_brings_back_its_own_agents_and_schedule(db, tenant_client):
    r = await tenant_client.post(WF, json={"name": "Daily", **_flow(WRITER, schedule={"cron": "0 9 * * *", "timezone": "UTC"})})
    assert r.status_code == 201, r.text
    wf = r.json()
    writer_id = next(n["agent_id"] for n in wf["nodes"] if n["id"] == "w")

    # v2: the writer is replaced (an AI edit makes a new own agent and drops the old one),
    # an approval step is added, and the schedule goes.
    v2 = _flow({**WRITER, "instructions": "Be formal."}, extra_step=True)
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json={**v2, "expected_version": 1})
    assert r.status_code == 200, r.text
    assert await db.get(BuilderAgent, writer_id) is None  # garbage-collected
    assert (await db.execute(select(func.count()).select_from(BuilderSchedule))).scalar_one() == 0
    [top, first] = (await tenant_client.get(f"{WF}/{wf['id']}/versions")).json()
    assert top["summary"] == "Added Check; changed Input, Writer" and first["note"] == "Created"

    r = await tenant_client.post(f"{WF}/{wf['id']}/versions/1/restore", json={"expected_version": 2})
    assert r.status_code == 200, r.text
    restored = r.json()
    assert restored["version"] == 3 and [n["id"] for n in restored["nodes"]] == ["start", "w", "out"]
    assert next(n["agent_id"] for n in restored["nodes"] if n["id"] == "w") == writer_id
    db.expire_all()
    writer = await db.get(BuilderAgent, writer_id)
    assert writer is not None and writer.instructions == "Be brief." and writer.workflow_id == wf["id"]
    # Only the restored graph's agents remain, and the schedule is back.
    owned = (await db.execute(select(BuilderAgent.id).where(BuilderAgent.workflow_id == wf["id"]))).scalars().all()
    assert owned == [writer_id]
    [sched] = (await db.execute(select(BuilderSchedule))).scalars().all()
    assert sched.enabled and sched.cron == "0 9 * * *"


async def test_a_version_pointing_at_a_deleted_agent_is_refused_unchanged(db, tenant_client, demo):
    shared = await make_agent(tenant_client, demo, ["echo"])
    nodes = [{"id": "start", "type": "input"}, {"id": "a", "type": "agent", "agent_id": shared["id"]}, {"id": "out", "type": "output"}]
    edges = [{"id": "e1", "source": "start", "target": "a"}, {"id": "e2", "source": "a", "target": "out"}]
    wf = (await tenant_client.post(WF, json={"name": "Uses shared", "nodes": nodes, "edges": edges})).json()
    await tenant_client.patch(f"{WF}/{wf['id']}", json={"nodes": [nodes[0], nodes[2]], "edges": [{"id": "e1", "source": "start", "target": "out"}]})
    assert (await tenant_client.delete(f"{A}/{shared['id']}")).status_code == 204

    r = await tenant_client.post(f"{WF}/{wf['id']}/versions/1/restore", json={})
    assert r.status_code == 422 and r.json()["problems"]
    now = (await tenant_client.get(f"{WF}/{wf['id']}")).json()
    assert now["version"] == 2 and len(now["nodes"]) == 2
