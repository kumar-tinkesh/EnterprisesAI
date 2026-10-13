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
