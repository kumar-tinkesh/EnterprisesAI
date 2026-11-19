"""Streaming: the answer's text as it's written ("output_delta" events), on
by default, off on request, never for an answer a guardrail has to check
first — and the callers' live view (SSE) on the public API and share links.
"""
from __future__ import annotations

import asyncio
import json

from builder.publishing.live import caller_events
from builder.runs.events import LocalEventBus, set_event_bus
from builder.tests.test_publishing import bearer, publish
from builder.tests.test_runs import demo, gateway, make_agent, reply, runtime, worker  # noqa: F401  (fixtures)
from builder.tests.test_shared import outsider

B = "/api/v1/builder"
P = "/api/v1/public"
S = "/api/v1/shared"


async def _run_collecting(runtime, client, agent, **body) -> tuple[str, list[dict]]:
    r = await client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "hi", **body})
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    events: list[dict] = []
    async with runtime["bus"].subscribe(run_id) as sub:
        await worker(runtime).drain()
        while (e := await sub.get(timeout=0.05)) is not None:
            events.append(e)
    return run_id, events


async def test_an_answer_streams_by_default_and_not_when_turned_off(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply(calls=[("demo__echo", {"text": "x"})]), reply("Hello there, here is the answer.")])
    _, events = await _run_collecting(runtime, tenant_client, agent)
    deltas = [e for e in events if e["type"] == "output_delta"]
    assert deltas and deltas[-1]["turn"] == 2 and deltas[0]["at"] == 0
    assert "".join(d["text"] for d in deltas if d["turn"] == 2) == "Hello there, here is the answer."

    gateway([reply("Quiet.")])
    _, events = await _run_collecting(runtime, tenant_client, agent, stream=False)
    assert not [e for e in events if e["type"] == "output_delta"]


async def test_an_answer_a_guardrail_checks_is_never_streamed(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [], guardrails={"pii_output": True})
    gateway([reply("Mail me at a@b.io")])
    run_id, events = await _run_collecting(runtime, tenant_client, agent)
    assert not [e for e in events if e["type"] == "output_delta"]  # the unscrubbed text never left the server
    assert "a@b.io" not in ((await tenant_client.get(f"{B}/runs/{run_id}")).json()["output_text"] or "")


def _thinking(text: str, thought: str, calls=None):
    r = reply(text, calls)
    r.reasoning = thought
    return r


async def test_the_models_thinking_streams_and_stays_on_the_run(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([_thinking("", "I should echo first.", [("demo__echo", {"text": "x"})]), _thinking("Done.", "Now I can answer.")])
    run_id, events = await _run_collecting(runtime, tenant_client, agent)
    thought = [e for e in events if e["type"] == "reasoning_delta"]
    assert [(e["turn"], e["at"]) for e in thought] == [(1, 0), (2, 0)]
    assert [e["text"] for e in thought] == ["I should echo first.", "Now I can answer."]
    # Sent before that turn's answer text.
    kinds = [e["type"] for e in events if e["type"] in ("reasoning_delta", "output_delta")]
    assert kinds[-2:] == ["reasoning_delta", "output_delta"]
    run = (await tenant_client.get(f"{B}/runs/{run_id}")).json()
    assert run["output"]["reasoning"] == "I should echo first.\n\nNow I can answer."
    assert run["output_text"] == "Done."


async def test_no_thinking_no_field_and_none_when_a_guardrail_checks_the_answer(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    gateway([reply("Plain.")])
    run_id, events = await _run_collecting(runtime, tenant_client, agent)
    assert not [e for e in events if e["type"] == "reasoning_delta"]
    assert "reasoning" not in ((await tenant_client.get(f"{B}/runs/{run_id}")).json()["output"] or {})

    guarded = await make_agent(tenant_client, demo, [], guardrails={"pii_output": True})
    gateway([_thinking("Fine.", "Their mail is a@b.io")])
    run_id, events = await _run_collecting(runtime, tenant_client, guarded)
    assert not [e for e in events if e["type"] == "reasoning_delta"]
    assert "reasoning" not in ((await tenant_client.get(f"{B}/runs/{run_id}")).json()["output"] or {})


async def test_callers_see_the_thinking_but_not_a_sub_agents():
    bus = LocalEventBus()
    set_event_bus(bus)
    try:
        states = iter([{"status": "running", "output": None}, {"status": "succeeded", "output": "Hi"}])

        async def view() -> dict:
            return next(states)

        async def produce():
            await asyncio.sleep(0.05)
            await bus.publish("r1", {"type": "reasoning_delta", "turn": 1, "at": 0, "text": "Greet them.", "node_id": "agent"})
            await bus.publish("r1", {"type": "reasoning_delta", "turn": 1, "at": 0, "text": "helper plan", "node_id": "agent", "via": "Helper"})
            await bus.publish("r1", {"type": "run_status", "status": "succeeded"})

        task = asyncio.create_task(produce())
        out = [chunk async for chunk in caller_events("r1", view, idle_seconds=1)]
        await task
    finally:
        set_event_bus(None)
    events = [(c.split("\n")[0], json.loads(c.split("data: ", 1)[1])) for c in out if c.startswith("event: thinking")]
    assert events == [("event: thinking", {"step": "agent", "turn": 1, "at": 0, "text": "Greet them."})]
    assert "helper plan" not in "".join(out)


async def test_a_published_run_shows_its_thinking(tenant_client, anon_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    key = await publish(tenant_client, "agents", agent["id"])
    gateway([_thinking("Hello!", "Greet them back.")])
    r = await anon_client.post(f"{P}/runs", headers=bearer(key), json={"input": "hi", "wait_seconds": 0})
    await worker(runtime).drain()
    view = (await anon_client.get(f"{P}/runs/{r.json()['run_id']}", headers=bearer(key))).json()
    assert (view["output"], view["reasoning"]) == ("Hello!", "Greet them back.")


async def test_live_view_sends_only_text_and_state():
    bus = LocalEventBus()
    set_event_bus(bus)
    try:
        states = iter([{"status": "running", "output": None}, {"status": "succeeded", "output": "Hi!"}])

        async def view() -> dict:
            return next(states)

        async def produce():
            await asyncio.sleep(0.05)
            await bus.publish("r1", {"type": "tool_call", "phase": "started", "tool": "secret", "arguments": {"pw": "x"}})
            await bus.publish("r1", {"type": "output_delta", "turn": 1, "at": 0, "text": "Hi", "node_id": "agent"})
            await bus.publish("r1", {"type": "run_status", "status": "succeeded"})

        task = asyncio.create_task(produce())
        out = [chunk async for chunk in caller_events("r1", view, idle_seconds=1)]
        await task
    finally:
        set_event_bus(None)
    text = "".join(out)
    assert "secret" not in text and "pw" not in text  # tool calls stay inside
    events = [(c.split("\n")[0], json.loads(c.split("data: ", 1)[1])) for c in out if c.startswith("event:")]
    assert events == [
        ("event: run", {"status": "running", "output": None}),
        ("event: doing", {"what": "tool"}),  # that a tool is in use, never which
        ("event: delta", {"turn": 1, "at": 0, "text": "Hi"}),
        ("event: run", {"status": "succeeded", "output": "Hi!"}),
    ]


async def test_callers_get_the_live_endpoints(tenant_client, anon_client, make_user_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], share=True)
    gateway([reply("Public answer."), reply("Shared answer.")])
    r = await anon_client.post(f"{P}/runs", headers=bearer(key), json={"input": "x", "wait_seconds": 0, "stream": True})
    visitor = await make_user_client(outsider())
    s = await visitor.post(f"{S}/{key['share_slug']}/runs", json={"input": "y", "wait_seconds": 0})
    await worker(runtime).drain()

    public = await anon_client.get(f"{P}/runs/{r.json()['run_id']}/events", headers=bearer(key))
    assert public.status_code == 200 and public.headers["content-type"].startswith("text/event-stream")
    assert "Public answer." in public.text and public.text.startswith("event: run")
    shared = await visitor.get(f"{S}/{key['share_slug']}/runs/{s.json()['run_id']}/events")
    assert "Shared answer." in shared.text
    # Someone else's run isn't theirs to watch.
    other = await make_user_client(outsider().model_copy(update={"id": "ou_2"}))
    assert (await other.get(f"{S}/{key['share_slug']}/runs/{s.json()['run_id']}/events")).status_code == 404


async def test_one_address_can_only_start_so_many_runs(tenant_client, anon_client, demo, monkeypatch):
    from builder.config import get_builder_settings

    monkeypatch.setattr(get_builder_settings(), "PUBLIC_RUNS_PER_IP_PER_MINUTE", 2)
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], requests_per_minute=100)
    codes = [(await anon_client.post(f"{P}/runs", headers=bearer(key), json={"input": "x", "wait_seconds": 0})).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


async def test_it_is_asked_for_a_plan_unless_turned_off(tenant_client, demo, gateway, runtime, monkeypatch):
    from builder.agents.prompts import PLAN_RULE
    from builder.config import get_builder_settings

    gw = gateway([reply("A."), reply("B."), reply("C."), reply("D.")])
    for agent in (
        await make_agent(tenant_client, demo, []),
        await make_agent(tenant_client, demo, [], chat={"show_plan": False}),
        await make_agent(tenant_client, demo, [], guardrails={"pii_output": True}),  # its thinking couldn't be shown
    ):
        await _run_collecting(runtime, tenant_client, agent)
    monkeypatch.setattr(get_builder_settings(), "AGENT_PLAN_THINKING", False)
    await _run_collecting(runtime, tenant_client, await make_agent(tenant_client, demo, []))
    asked = [PLAN_RULE in r.messages[0].content for r in gw.requests]
    assert asked == [True, False, False, False]


async def test_thinking_is_kept_and_shown_without_streaming_too(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    gateway([_thinking("Answer.", "Short plan.")])
    run_id, events = await _run_collecting(runtime, tenant_client, agent, stream=False)
    assert [(e["turn"], e["at"], e["text"]) for e in events if e["type"] == "reasoning_delta"] == [(1, 0, "Short plan.")]
    assert (await tenant_client.get(f"{B}/runs/{run_id}")).json()["output"]["reasoning"] == "Short plan."


async def test_a_plan_tag_never_closed_is_the_answer(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    gateway([_thinking("", "The whole answer ended up inside the tag.")])
    run_id, _ = await _run_collecting(runtime, tenant_client, agent)
    run = (await tenant_client.get(f"{B}/runs/{run_id}")).json()
    assert run["output_text"] == "The whole answer ended up inside the tag."
    assert "reasoning" not in (run["output"] or {})
