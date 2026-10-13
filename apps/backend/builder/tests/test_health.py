"""Health: how ready an agent or workflow is, from what's stored about it."""
from __future__ import annotations

from builder.tests.test_runs import demo, gateway, make_agent, reply, runtime, start, worker  # noqa: F401  (fixtures)

B = "/api/v1/builder"


async def test_a_fresh_agent_is_not_tested_and_says_what_to_fix(tenant_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo", "send_note"])
    h = (await tenant_client.get(f"{B}/agents/{agent['id']}/health")).json()
    assert h["status"] == "not_tested" and h["runs_counted"] == 0
    dims = {d["key"]: d for d in h["dimensions"]}
    assert set(dims) == {"identity", "abilities", "safety", "reliability", "testing", "observability"}
    # Nothing to go on yet: not measured, and kept out of the score.
    assert not dims["reliability"]["measured"] and not dims["testing"]["measured"]
    assert dims["abilities"]["score"] == 100 and dims["abilities"]["summary"] == "2 tools"
    assert dims["identity"]["score"] == 50 and "Missing: its goal says what done looks like" in dims["identity"]["detail"]
    # It can write (send_note) with the override guard off: that blocks.
    assert [b["key"] for b in h["blockers"]] == ["writes_without_injection_guard"]
    assert 0 < h["score"] < 100


async def test_runs_fill_in_reliability(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"], guardrails={"injection": True})
    gateway([reply(f"Answer {i}.") for i in range(5)])
    for i in range(5):
        await start(tenant_client, agent, f"q{i}")
    await worker(runtime).drain()
    h = (await tenant_client.get(f"{B}/agents/{agent['id']}/health")).json()
    dims = {d["key"]: d for d in h["dimensions"]}
    assert dims["reliability"]["score"] == 100 and dims["reliability"]["summary"] == "100% of 5 runs succeeded"
    assert h["blockers"] == [] and h["runs_counted"] == 5
    # Run enough, but never tested: still "testing", not ready.
    assert h["status"] == "testing"


async def test_workflow_health_checks_its_structure(tenant_client):
    r = await tenant_client.post(f"{B}/workflows", json={"name": "Empty", "nodes": [], "edges": []})
    wf = r.json()
    h = (await tenant_client.get(f"{B}/workflows/{wf['id']}/health")).json()
    dims = {d["key"]: d for d in h["dimensions"]}
    assert dims["structure"]["score"] == 0 and dims["structure"]["summary"] == "Empty: no steps yet"
    assert h["status"] == "not_tested"
