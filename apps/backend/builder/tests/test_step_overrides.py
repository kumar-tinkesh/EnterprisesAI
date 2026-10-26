"""A workflow step's ``config_overrides`` reach the model: each setting the
Configure popup offers changes what the step's agent actually sends."""
from __future__ import annotations

from builder.tests.test_runs import demo, get_run, reply, runtime, worker  # noqa: F401  (fixtures)
from builder.tests.test_workflows import INPUT, OUTPUT, agent, llm, start, workflow  # noqa: F401  (fixtures)


async def test_a_steps_overrides_change_what_its_agent_sends(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer", llm={"temperature": 0.2})
    llm.when("You are Writer", "Done.").when("Check the AI RESPONSE", '{"violations": []}')
    overrides = {
        "llm": {"temperature": 1.1, "max_output_tokens": 300},
        "response": {"language": "Hindi", "citations": "off"},
        "guardrails": {"custom_rules": ["Never mention prices"]},
    }
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": overrides}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    run_id = await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded", (run["error"], [(n["node_id"], n["error"]) for n in run["nodes"]])

    sent = llm.calls("You are Writer")[0]
    system = sent.messages[0].content
    assert sent.temperature == 1.1 and sent.max_tokens == 300
    assert "Answer in Hindi" in system and "Do not add source citations." in system
    assert "Never mention prices" in system


async def test_a_steps_fallback_model_answers_when_the_agents_model_fails(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", RuntimeError("model is down"), "From the fallback.")
    overrides = {"reliability": {"fallback_model": "gpt-4o-mini"}}
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": overrides}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    run_id = await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "From the fallback."
    assert [r.model for r in llm.calls("You are Writer")][-1] == "gpt-4o-mini"


async def test_thinking_effort_reaches_the_model_and_auto_sends_none(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "Done.")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": {"llm": {"reasoning_effort": "high"}}}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    await start(tenant_client, wf, "write")
    plain = await workflow(tenant_client, [INPUT, {"id": "w", "type": "agent", "agent_id": writer}, OUTPUT], [("in", "w"), ("w", "out")])
    await start(tenant_client, plain, "write")
    await worker(runtime).drain()
    assert sorted(str(r.reasoning_effort) for r in llm.calls("You are Writer")) == ["None", "high"]


async def test_a_step_can_run_its_agent_on_another_model(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "Done.")
    overrides = {"llm_model": "gpt-4.1-nano", "llm": {"temperature": 0.9}}
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": overrides}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    assert not [p for p in wf.get("problems", []) if p.get("node_id") == "w"]
    run_id = await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    sent = llm.calls("You are Writer")[0]
    assert (sent.model, sent.temperature) == ("gpt-4.1-nano", 0.9)


async def test_a_step_can_turn_on_its_agents_memory(tenant_client, llm, runtime):
    from builder.agents.memory import MEMORY_TOOL

    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "Done.")
    for overrides in ({"memory": {"enabled": True}}, None):
        wf = await workflow(
            tenant_client,
            [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": overrides}, OUTPUT],
            [("in", "w"), ("w", "out")],
        )
        await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    offered = sorted(any(t.name == MEMORY_TOOL for t in r.tools or []) for r in llm.calls("You are Writer"))
    assert offered == [False, True]



async def test_a_step_retries_the_model_only_on_the_errors_it_names(tenant_client, llm, runtime):
    retrying = await agent(tenant_client, "Patient")
    picky = await agent(tenant_client, "Picky")
    llm.when("You are Patient", RuntimeError("429 rate limit hit"), "Got through.").when("You are Picky", RuntimeError("429 rate limit hit"))
    runs = []
    for agent_id, retry_on in ((retrying, ["rate_limit"]), (picky, ["server"])):
        overrides = {"reliability": {"retries": 2, "retry_on": retry_on}}
        wf = await workflow(
            tenant_client,
            [INPUT, {"id": "w", "type": "agent", "agent_id": agent_id, "config_overrides": overrides}, OUTPUT],
            [("in", "w"), ("w", "out")],
        )
        runs.append(await start(tenant_client, wf, "write"))
    await worker(runtime).drain()

    ok, failed = [await get_run(tenant_client, r) for r in runs]
    assert ok["status"] == "succeeded" and ok["output_text"] == "Got through."
    assert len(llm.calls("You are Patient")) == 2
    assert failed["status"] == "failed" and len(llm.calls("You are Picky")) == 1


async def test_stop_words_and_formatting_reach_the_model(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "Done.")
    overrides = {"llm": {"stop_sequences": ["END"]}, "response": {"formats": ["bullets"]}}
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": overrides}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    sent = llm.calls("You are Writer")[0]
    assert sent.stop == ["END"]
    assert "Formatting: use ONLY bullets. Do not use code, markdown, tables." in sent.messages[0].content


async def test_a_step_limits_its_agents_tool_calls(tenant_client, demo, llm, runtime):
    writer = await agent(tenant_client, "Writer", demo, ["echo"])
    call = reply(calls=[("demo__echo", {"text": "hi"})])
    llm.when("You are Writer", call, call, "Done.")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": {"tools": {"max_calls": 1}}}, OUTPUT],
        [("in", "w"), ("w", "out")],
    )
    run_id = await start(tenant_client, wf, "write")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded", run["error"]
    assert [c["tool_name"] for c in run["tool_calls"]] == ["echo"]
    assert llm.calls("You are Writer")[-1].tools is None  # out of calls: asked to answer


async def test_a_step_can_stop_on_a_failing_tool_or_a_slow_one(tenant_client, demo, llm, runtime):
    stopper = await agent(tenant_client, "Stopper", demo, ["fail"])
    waiter = await agent(tenant_client, "Waiter", demo, ["wait_for"])
    llm.when("You are Stopper", reply(calls=[("demo__fail", {})]), "Never reached.")
    llm.when("You are Waiter", reply(calls=[("demo__wait_for", {"seconds": 30})]), "Gave up waiting.")
    runs = []
    for agent_id, overrides in ((stopper, {"tools": {"on_failure": "stop"}}), (waiter, {"tools": {"timeout_seconds": 5}})):
        wf = await workflow(
            tenant_client,
            [INPUT, {"id": "w", "type": "agent", "agent_id": agent_id, "config_overrides": overrides}, OUTPUT],
            [("in", "w"), ("w", "out")],
        )
        runs.append(await start(tenant_client, wf, "go"))
    await worker(runtime).drain()

    stopped, waited = [await get_run(tenant_client, r) for r in runs]
    assert stopped["status"] == "failed" and "fail failed" in stopped["error"]
    assert waited["status"] == "succeeded" and waited["output_text"] == "Gave up waiting."
    [slow] = waited["tool_calls"]
    assert slow["status"] != "succeeded"

# ── Trying one step by itself (the canvas's Test) ───────────────────────────


async def test_one_step_runs_by_itself_as_it_is_on_the_canvas(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "A test answer.").when("You are Drafty", "From the draft.")
    wf = await workflow(tenant_client, [INPUT, {"id": "w", "type": "agent", "agent_id": writer}, OUTPUT], [("in", "w"), ("w", "out")])
    url = f"/api/v1/builder/workflows/{wf['id']}/steps/test"

    # Unsaved edits run: an override on the saved agent...
    r = await tenant_client.post(url, json={"node": {"id": "w", "type": "agent", "agent_id": writer, "config_overrides": {"llm": {"temperature": 1.3}}}, "input": "hi"})
    assert r.status_code == 202, r.text
    saved_run = r.json()["id"]
    # ...and a new agent that only exists as a draft on the step.
    draft = {"name": "Drafty", "role": "helper", "goal": "help", "config": {}}
    r = await tenant_client.post(url, json={"node": {"id": "n9", "type": "agent", "draft_agent": draft}, "input": "hi"})
    assert r.status_code == 202, r.text
    draft_run = r.json()["id"]
    await worker(runtime).drain()

    for run_id, answer in ((saved_run, "A test answer."), (draft_run, "From the draft.")):
        run = await get_run(tenant_client, run_id)
        assert run["status"] == "succeeded", run
        assert run["output_text"] == answer and run["purpose"] == "step"
    assert llm.calls("You are Writer")[0].temperature == 1.3
    # Not in run history.
    listed = (await tenant_client.get("/api/v1/builder/runs", params={"workflow_id": wf["id"]})).json()
    assert not {saved_run, draft_run} & {x["id"] for x in listed}


async def test_a_tool_step_runs_by_itself_and_other_steps_cannot(tenant_client, demo, llm, runtime):
    wf = await workflow(tenant_client, [INPUT, OUTPUT], [("in", "out")])
    url = f"/api/v1/builder/workflows/{wf['id']}/steps/test"
    step = {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:echo", "tool_args": {"text": "namaste"}}
    r = await tenant_client.post(url, json={"node": step, "input": "say it"})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()
    run = await get_run(tenant_client, r.json()["id"])
    assert run["status"] == "succeeded", run
    assert "namaste" in run["output_text"]

    r = await tenant_client.post(url, json={"node": {"id": "c", "type": "condition"}, "input": "x"})
    assert r.status_code == 422
    r = await tenant_client.post(url, json={"node": {"id": "t", "type": "tool", "tool_id": "mcp:nope:echo"}, "input": "x"})
    assert r.status_code == 422 and r.json()["problems"]
