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
