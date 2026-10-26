"""Dashboard insights: the caller's runs, this window vs the previous one."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from builder.models import BuilderRun
from builder.runs.db import utcnow
from builder.tests.test_runs import demo, gateway, make_agent, reply, runtime, start, worker  # noqa: F401  (fixtures)

B = "/api/v1/builder"


async def test_insights_compare_windows_and_rank_agents(db, tenant_client, demo, gateway, runtime):
    empty = (await tenant_client.get(f"{B}/insights")).json()
    assert empty["current"]["runs"] == 0 and empty["all_time"] == {"runs": 0, "success_rate": 0.0}
    assert len(empty["series"]) == 14 and empty["busiest"] == []

    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("One."), reply("Two."), reply("Three.")])
    ids = [await start(tenant_client, agent, f"q{i}") for i in range(3)]
    await worker(runtime).drain()
    # One of them ran ten days ago: it belongs to the previous window.
    await db.execute(update(BuilderRun).where(BuilderRun.id == ids[0]).values(created_at=utcnow() - timedelta(days=10)))
    await db.commit()

    out = (await tenant_client.get(f"{B}/insights", params={"days": 7})).json()
    assert (out["current"]["runs"], out["current"]["succeeded"], out["current"]["active"]) == (2, 2, 1)
    assert out["current"]["success_rate"] == 1.0 and out["previous"]["runs"] == 1
    assert sum(d["succeeded"] for d in out["series"]) == 3 and out["series"][-1]["succeeded"] == 2
    assert out["busiest"] == [{"kind": "agent", "id": agent["id"], "name": "Helper", "exists": True, "runs": 3, "succeeded": 3}]
    assert out["all_time"] == {"runs": 3, "success_rate": 1.0}

    # A deleted agent keeps the name it ran under.
    await tenant_client.delete(f"{B}/agents/{agent['id']}")
    [top] = (await tenant_client.get(f"{B}/insights")).json()["busiest"]
    assert (top["name"], top["exists"]) == ("Helper", False)


async def test_overview_has_a_line_per_agent(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    idle = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("One."), reply("Two.")])
    for i in range(2):
        await start(tenant_client, agent, f"q{i}")
    await worker(runtime).drain()

    out = (await tenant_client.get(f"{B}/overview")).json()
    by_id = {i["id"]: i for i in out["items"]}
    busy, quiet = by_id[agent["id"]], by_id[idle["id"]]
    assert (busy["runs"], busy["succeeded"], busy["daily"][-1], busy["last_status"]) == (2, 2, 2, "succeeded")
    assert busy["health_status"] == "testing" and busy["running"] == 0 and busy["schedule"] is None and busy["published"] == 0
    assert (quiet["runs"], quiet["last_run_at"], quiet["health_status"]) == (0, None, "not_tested")
    assert out["totals"] == {"runs": 2, "succeeded": 2, "failed": 0, "running": 0, "waiting": 0}
