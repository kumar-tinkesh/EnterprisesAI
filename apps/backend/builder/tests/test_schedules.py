"""Schedules: cron handling, the API, workflow sync, and firing exactly once.

Firing is driven directly (``fire_due``) with the schedule made due by moving
its ``next_run_at`` into the past, then the run is executed by a worker like
any other — the tool calls are the real demo MCP server's.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from builder.models import BuilderRun, BuilderSchedule
from builder.runs.db import as_utc, utcnow
from builder.schedules import cron
from builder.schedules.service import fire_due
from builder.tests.test_runs import demo, gateway, get_run, make_agent, reply, runtime, worker  # noqa: F401  (fixtures)
from vendor.services import mcp_auth

S = "/api/v1/builder/schedules"
WF = "/api/v1/builder/workflows"


async def make_due(db, schedule_id: str) -> None:
    await db.execute(update(BuilderSchedule).where(BuilderSchedule.id == schedule_id).values(next_run_at=utcnow() - timedelta(minutes=1)))
    await db.commit()


async def schedule_row(db, schedule_id: str) -> BuilderSchedule:
    db.expire_all()
    return (await db.execute(select(BuilderSchedule).where(BuilderSchedule.id == schedule_id))).scalars().one()


# ── cron ─────────────────────────────────────────────────────────────────────


def test_cron_checks_and_words():
    cron.validate("0 9 * * 1-5", "Asia/Kolkata")
    cron.validate("0 9 * * 1-5", "Asia/Calcutta")  # what Chrome often reports (old alias; needs tzdata)
    for bad, tz in [("0 9 * *", "UTC"), ("0 0 9 * * *", "UTC"), ("61 * * * *", "UTC"), ("0 9 * * *", "Mars/Base"), ("* * * * *", "UTC")]:
        with pytest.raises(cron.ScheduleError):
            cron.validate(bad, tz)
    assert cron.describe("0 9 * * 1-5") == "Weekdays at 9:00 AM"
    assert cron.describe("30 18 * * *") == "Every day at 6:30 PM"
    assert cron.describe("0 8 * * 1") == "Every Monday at 8:00 AM"
    assert cron.describe("*/15 * * * *") == "Every 15 minutes"
    assert cron.describe("0 9 1 * *") == "Monthly on day 1 at 9:00 AM"


def test_next_run_is_in_the_schedules_own_timezone():
    after = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    # 9:00 in India = 03:30 UTC.
    assert cron.next_run("0 9 * * *", "Asia/Kolkata", after) == datetime(2026, 10, 9, 3, 30, tzinfo=timezone.utc)
    # Across the US DST change (Nov 1 2026), 9:00 New York moves from 13:00 to 14:00 UTC.
    before = cron.next_run("0 9 * * *", "America/New_York", datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc))
    after_dst = cron.next_run("0 9 * * *", "America/New_York", datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc))
    assert (before.hour, after_dst.hour) == (13, 14)


async def test_preview(tenant_client):
    ok = (await tenant_client.post(f"{S}/preview", json={"cron": "0 9 * * 1-5", "timezone": "Asia/Kolkata"})).json()
    assert ok["ok"] and ok["description"] == "Weekdays at 9:00 AM" and len(ok["next_runs"]) == 3
    bad = (await tenant_client.post(f"{S}/preview", json={"cron": "every day", "timezone": "UTC"})).json()
    assert not bad["ok"] and bad["error"]


# ── agent schedules ──────────────────────────────────────────────────────────


async def test_agent_schedule_fires_once_and_moves_on(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    r = await tenant_client.post(S, json={"agent_id": agent["id"], "cron": "0 9 * * *", "timezone": "Asia/Kolkata", "input": "say hi"})
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["enabled"] and sched["editable"] and sched["description"] == "Every day at 9:00 AM"
    # Always sent with its zone (SQLite stores it without one), or the browser misreads it.
    assert datetime.fromisoformat(sched["next_run_at"].replace("Z", "+00:00")).tzinfo is not None
    assert datetime.fromisoformat(sched["next_run_at"].replace("Z", "+00:00")) > utcnow()

    await make_due(db, sched["id"])
    gateway([reply(calls=[("demo__echo", {"text": "hi"})]), reply("Said hi.")])
    # Two workers polling at the same moment still start one run.
    started = await asyncio.gather(fire_due(), fire_due())
    assert sorted(started) == [0, 1]
    [run] = (await db.execute(select(BuilderRun))).scalars().all()
    assert run.schedule_id == sched["id"] and run.input["text"] == "say hi"
    run_id = run.id

    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    row = await schedule_row(db, sched["id"])
    assert (row.last_status, row.last_run_id, row.last_error) == ("started", run_id, None)
    assert as_utc(row.next_run_at) > utcnow()
    assert await fire_due() == 0  # not due again yet


async def test_a_schedule_that_cannot_run_is_skipped_with_the_reason(db, tenant_client, demo, tenant_user):
    agent = await make_agent(tenant_client, demo, ["echo"])
    sched = (await tenant_client.post(S, json={"agent_id": agent["id"], "cron": "0 9 * * *", "input": "x"})).json()
    await mcp_auth.delete_user_credential(db, server_id=demo.id, user_id=tenant_user.id)
    await db.commit()
    await make_due(db, sched["id"])

    assert await fire_due() == 0
    assert (await db.execute(select(BuilderRun))).scalars().first() is None
    row = await schedule_row(db, sched["id"])
    assert row.last_status == "skipped" and "connect" in row.last_error.lower()
    assert row.enabled and as_utc(row.next_run_at) > utcnow()  # tries again next time


async def test_change_pause_run_now_and_delete(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    sched = (await tenant_client.post(S, json={"agent_id": agent["id"], "cron": "0 9 * * *", "input": "x"})).json()

    r = await tenant_client.patch(f"{S}/{sched['id']}", json={"enabled": False})
    assert r.json()["enabled"] is False and r.json()["next_run_at"] is None
    r = await tenant_client.patch(f"{S}/{sched['id']}", json={"enabled": True, "cron": "30 18 * * 1-5", "input": "y"})
    assert r.json()["description"] == "Weekdays at 6:30 PM" and r.json()["next_run_at"] and r.json()["input"]["text"] == "y"
    assert (await tenant_client.patch(f"{S}/{sched['id']}", json={"cron": "* * * * *"})).status_code == 422

    gateway([reply("done")])
    r = await tenant_client.post(f"{S}/{sched['id']}/run")
    assert r.status_code == 200, r.text
    await worker(runtime).drain()
    assert (await get_run(tenant_client, r.json()["run_id"]))["status"] == "succeeded"

    assert (await tenant_client.get(S, params={"agent_id": agent["id"]})).json()[0]["last_status"] == "started"
    assert (await tenant_client.delete(f"{S}/{sched['id']}")).status_code == 204
    assert (await tenant_client.get(S, params={"agent_id": agent["id"]})).json() == []


async def test_only_the_owner_changes_it_and_it_goes_with_the_agent(db, tenant_client, make_user_client, demo, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, ["echo"])
    sched = (await tenant_client.post(S, json={"agent_id": agent["id"], "cron": "0 9 * * *", "input": "x"})).json()
    admin = await make_user_client(CurrentUser(id="tu_2", email="a@x.io", full_name="A", role="tenant_admin", tenant_id=tenant.id))
    [seen] = (await admin.get(S, params={"agent_id": agent["id"]})).json()
    assert seen["is_mine"] is False and seen["editable"] is False
    assert (await admin.patch(f"{S}/{sched['id']}", json={"enabled": False})).status_code == 403
    assert (await admin.delete(f"{S}/{sched['id']}")).status_code == 403
    assert (await admin.post(f"{S}/{sched['id']}/run")).status_code == 403

    assert (await tenant_client.delete(f"/api/v1/builder/agents/{agent['id']}")).status_code == 204
    assert (await db.execute(select(BuilderSchedule))).scalars().first() is None


# ── workflow schedules (the Schedule trigger step) ───────────────────────────


def _graph(schedule: dict | None, trigger: str = "schedule_trigger") -> dict:
    t = {"id": "start", "type": trigger, "position": {"x": 0, "y": 0}}
    if schedule is not None:
        t["schedule"] = schedule
    return {
        "nodes": [t, {"id": "out", "type": "output", "position": {"x": 300, "y": 0}}],
        "edges": [{"id": "e1", "source": "start", "target": "out"}],
    }


async def test_workflow_schedule_follows_its_trigger_step(db, tenant_client, runtime):
    r = await tenant_client.post(WF, json={"name": "Daily", **_graph({"cron": "0 9 * * *", "timezone": "Asia/Kolkata", "input": "morning report"})})
    assert r.status_code == 201, r.text
    wf = r.json()
    [s] = (await tenant_client.get(S, params={"workflow_id": wf["id"]})).json()
    assert (s["kind"], s["node_id"], s["enabled"], s["editable"], s["input"]["text"]) == ("workflow", "start", True, False, "morning report")
    assert (await tenant_client.patch(f"{S}/{s['id']}", json={"enabled": False})).status_code == 409

    # It fires and the workflow runs as its owner.
    await make_due(db, s["id"])
    assert await fire_due() == 1
    await worker(runtime).drain()
    [run] = (await db.execute(select(BuilderRun))).scalars().all()
    assert (run.kind, run.schedule_id) == ("workflow", s["id"])
    assert (await get_run(tenant_client, run.id))["status"] == "succeeded"
    db.expire_all()

    # Switched off on the step -> paused; a bad cron can't be saved.
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json=_graph({"cron": "0 9 * * *", "enabled": False}))
    assert r.status_code == 200, r.text
    [s] = (await tenant_client.get(S, params={"workflow_id": wf["id"]})).json()
    assert s["enabled"] is False and s["next_run_at"] is None
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json=_graph({"cron": "every morning"}))
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "bad_schedule"

    # No cron yet is fine (saved, not scheduled); a different trigger removes it.
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json=_graph({}))
    assert r.status_code == 200
    assert (await tenant_client.get(S, params={"workflow_id": wf["id"]})).json()[0]["enabled"] is False
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json=_graph(None, trigger="input"))
    assert r.status_code == 200
    assert (await tenant_client.get(S, params={"workflow_id": wf["id"]})).json() == []


async def test_deleting_a_workflow_removes_its_schedule(db, tenant_client):
    wf = (await tenant_client.post(WF, json={"name": "Daily", **_graph({"cron": "0 9 * * *"})})).json()
    assert (await tenant_client.delete(f"{WF}/{wf['id']}")).status_code == 204
    assert (await db.execute(select(BuilderSchedule))).scalars().first() is None
