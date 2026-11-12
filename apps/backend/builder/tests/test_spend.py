"""This month's spend and the person's own monthly limit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from builder.models import BuilderRun
from builder.runs.db import utcnow
from builder.spend import month_start, next_month, previous_month
from builder.tests.test_runs import demo, gateway, make_agent, reply, runtime, start, worker  # noqa: F401  (fixtures)

B = "/api/v1/builder"


def test_month_edges():
    nov = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    assert month_start(nov) == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert next_month(nov) == datetime(2026, 12, 1, tzinfo=timezone.utc)
    dec = datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)
    assert next_month(dec) == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert previous_month(datetime(2027, 1, 5, tzinfo=timezone.utc)) == datetime(2026, 12, 1, tzinfo=timezone.utc)


async def test_spend_adds_up_this_month_and_the_limit_stops_new_runs(db, tenant_client, demo, gateway, runtime):
    empty = (await tenant_client.get(f"{B}/spend")).json()
    assert (empty["spent_usd"], empty["limit_usd"], empty["status"], empty["by_item"]) == (0.0, None, "ok", [])

    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("One."), reply("Two."), reply("Three.")])
    ids = [await start(tenant_client, agent, f"q{i}") for i in range(3)]
    await worker(runtime).drain()
    # Give them known costs: two this month, one last month.
    await db.execute(update(BuilderRun).values(cost_usd=0.40))
    last_month = month_start() - timedelta(days=3)
    await db.execute(update(BuilderRun).where(BuilderRun.id == ids[0]).values(created_at=last_month))
    await db.commit()

    out = (await tenant_client.get(f"{B}/spend")).json()
    assert (out["spent_usd"], out["last_month_usd"], out["runs"]) == (0.8, 0.4, 2)
    assert out["by_item"] == [{"kind": "agent", "id": agent["id"], "name": "Helper", "exists": True, "runs": 2, "cost_usd": 0.8}]
    assert round(sum(d["cost_usd"] for d in out["daily"]), 6) == 0.8 and out["daily"][-1]["date"] == utcnow().date().isoformat()

    # 80% of the limit -> "near"; at the limit -> "over" and new runs wait.
    r = await tenant_client.put(f"{B}/spend/limit", json={"monthly_usd": 1})
    assert (r.json()["limit_usd"], r.json()["status"]) == (1.0, "near")
    assert (await tenant_client.put(f"{B}/spend/limit", json={"monthly_usd": -1})).status_code == 422
    out = (await tenant_client.put(f"{B}/spend/limit", json={"monthly_usd": 0.8})).json()
    assert out["status"] == "over"
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "one more"})
    assert r.status_code == 422, r.text
    [problem] = r.json()["problems"]
    assert problem["code"] == "spend_limit" and "$0.80" in problem["message"]

    # Raised (or removed) -> runs start again.
    out = (await tenant_client.put(f"{B}/spend/limit", json={"monthly_usd": None})).json()
    assert (out["limit_usd"], out["status"]) == (None, "ok")
    gateway([reply("Four.")])
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "one more"})
    assert r.status_code == 202, r.text
