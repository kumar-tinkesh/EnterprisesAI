"""Workflow Settings: run-time limit, failure fallback, step summary, approval
overrides, the workflow's own knowledge, and answer depth."""
from __future__ import annotations

from builder.tests.test_runs import demo, get_run, runtime, worker  # noqa: F401  (fixtures)
from builder.tests.test_workflows import INPUT, OUTPUT, agent, llm, start, workflow  # noqa: F401  (fixtures)

WF = "/api/v1/builder/workflows"


async def test_defaults_mean_no_time_limit(tenant_client):
    wf = await workflow(tenant_client, [INPUT, OUTPUT], [("in", "out")])
    cfg = wf["config"]
    assert cfg["max_run_seconds"] is None and cfg["node_retry_fallback"] == "abort" and cfg["include_step_summary"] is False
    assert cfg["approval_overrides"] == {"read": "default", "edit": "default", "delete": "default"}
    bad = await tenant_client.post(WF, json={"name": "x", "nodes": [INPUT, OUTPUT], "edges": [{"id": "e", "source": "in", "target": "out"}],
                                             "config": {"approval_overrides": {"edit": "sometimes"}}})
    assert bad.status_code == 422


async def test_retries_then_skip(tenant_client, demo, runtime):
    wf = await workflow(
        tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:fail"}, OUTPUT], [("in", "t"), ("t", "out")],
        on_node_failure="retry", node_retry_count=1, node_retry_fallback="skip",
    )
    run_id = await start(tenant_client, wf, "go")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded"
    assert [n["status"] for n in run["nodes"] if n["node_id"] == "t"] == ["failed", "failed"]  # tried twice, then skipped


async def test_step_summary_and_answer_depth(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "Draft ready.")
    wf = await workflow(tenant_client, [INPUT, {"id": "a", "type": "agent", "agent_id": writer}, OUTPUT], [("in", "a"), ("a", "out")],
                        include_step_summary=True)
    r = await tenant_client.post(f"{WF}/{wf['id']}/runs", json={"input": "go", "depth": "short"})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()
    run = await get_run(tenant_client, r.json()["id"])
    assert run["output_text"].startswith("Draft ready.") and "**Step by step**" in run["output_text"] and "**Writer**\nDraft ready." in run["output_text"]
    assert "a sentence or two" in llm.calls("You are Writer")[0].messages[0].content


async def test_approval_overrides_decide_for_every_step(tenant_client, demo, runtime):
    note = {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:send_note", "tool_args": {"text": "hi"}}
    never = await workflow(tenant_client, [INPUT, note, OUTPUT], [("in", "t"), ("t", "out")], approval_overrides={"edit": "never"})
    run_id = await start(tenant_client, never, "go")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    assert runtime["notes"].read_text().strip() == "hi"  # ran without asking

    always = await workflow(tenant_client, [INPUT, note, OUTPUT], [("in", "t"), ("t", "out")],
                            approvals={"read": False, "edit": False, "delete": False}, approval_overrides={"edit": "always"})
    run_id = await start(tenant_client, always, "go")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "waiting"


async def test_the_workflows_own_knowledge(db, tenant_client, llm, runtime):
    from knowledge.models import KnowledgeBase

    writer = await agent(tenant_client, "Writer")
    wf = await workflow(tenant_client, [INPUT, {"id": "a", "type": "agent", "agent_id": writer}, OUTPUT], [("in", "a"), ("a", "out")])
    assert (await tenant_client.get(f"{WF}/{wf['id']}/knowledge")).json() == {"knowledge_base_id": None}
    kb_id = (await tenant_client.post(f"{WF}/{wf['id']}/knowledge")).json()["knowledge_base_id"]
    assert (await tenant_client.post(f"{WF}/{wf['id']}/knowledge")).json()["knowledge_base_id"] == kb_id  # made once
    kb = await db.get(KnowledgeBase, kb_id)
    assert kb.name == "Flow · workflow knowledge"

    llm.when("You are Writer", "ok")
    run_id = await start(tenant_client, wf, "go")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    # The step's agent (with no knowledge of its own) was given the workflow's.
    assert [t.name for t in llm.calls("You are Writer")[0].tools or []] == ["search_knowledge"]

    assert (await tenant_client.delete(f"{WF}/{wf['id']}")).status_code == 204
    db.expire_all()
    assert await db.get(KnowledgeBase, kb_id) is None
