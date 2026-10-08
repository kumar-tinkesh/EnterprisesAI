"""Agent runs end to end: worker, leases, approvals, crash recovery, events.

The model is scripted (no LLM needed); the tools are the REAL demo MCP server
over stdio, so tool calls, approvals and their side effects (notes.txt in the
user's home) are real. "Killing a worker" is done the way a crash looks to the
system: the worker's tasks are cancelled with its lease still held, then the
lease is made to lapse and another worker takes over.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import User

from apps.llm_gateway.types import CompletionResponse, TokenUsage, ToolCall
from builder.config import get_builder_settings
from builder.models import BuilderApproval, BuilderRun, BuilderToolCall
from builder.runs import db as runs_db
from builder.runs import states
from builder.runs.db import utcnow
from builder.runs.events import LocalEventBus, set_event_bus
from builder.runs.queue import LocalQueue, set_run_queue
from builder.runs.worker import Worker
from builder.services.tool_runtime import shutdown_pool
from vendor.models import VendorMCPServer
from vendor.services import mcp_auth, mcp_service

FIXTURE = Path(__file__).parent / "fixtures" / "demo_mcp_server.py"
HANG = object()


class ScriptedGateway:
    """Returns the scripted replies in order; HANG blocks forever (a stuck model call)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.requests = []
        self.hung = asyncio.Event()

    async def complete(self, request, provider=None, fallback=True):
        self.requests.append(request)
        item = self.script.pop(0)
        if item is HANG:
            self.hung.set()
            await asyncio.Event().wait()
        if isinstance(item, BaseException):
            raise item
        return item


def reply(text: str = "", calls: list[tuple[str, dict]] | None = None) -> CompletionResponse:
    import json

    return CompletionResponse(
        content=text,
        tool_calls=[ToolCall(id=f"call-{i}-{name}", name=name, arguments=json.dumps(args)) for i, (name, args) in enumerate(calls or [])],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest_asyncio.fixture(autouse=True)
async def runtime(db, tmp_path, monkeypatch, tenant):
    settings = get_builder_settings()
    monkeypatch.setattr(settings, "BUILDER_USER_HOME_ROOT", str(tmp_path / "homes"))
    monkeypatch.setattr(settings, "AGENT_MODEL_RETRY_DELAY_SECONDS", 0.0)

    async def no_embedding(tool, **_):
        return False

    monkeypatch.setattr(mcp_service, "embed_tool", no_embedding)
    runs_db.set_session_factory(async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False))
    queue, bus = LocalQueue(), LocalEventBus()
    set_run_queue(queue)
    set_event_bus(bus)
    db.add(User(id="tu_1", tenant_id=tenant.id, email="tu@x.io", full_name="Tenant User", role="tenant_user"))
    await db.commit()
    yield {"queue": queue, "bus": bus, "notes": tmp_path / "homes" / "tu_1" / "notes.txt"}
    await shutdown_pool()
    runs_db.set_session_factory(None)
    set_run_queue(None)
    set_event_bus(None)


@pytest.fixture
def gateway(monkeypatch):
    def install(script: list) -> ScriptedGateway:
        gw = ScriptedGateway(script)
        monkeypatch.setattr("builder.agents.runtime._gateway", lambda: gw)
        return gw

    return install


@pytest_asyncio.fixture
async def demo(db, tenant_user):
    server = VendorMCPServer(
        name="demo", description="demo", is_global=True, transport="stdio", auth_type="env",
        auth_config={}, command=sys.executable, args=[str(FIXTURE)],
    )
    db.add(server)
    await db.flush()
    await mcp_service.test_mcp_connection(db, server=server)
    await mcp_auth.store_server_credentials(db, server_id=server.id, credentials={}, tenant_id=tenant_user.tenant_id, user_id=tenant_user.id)
    await db.commit()
    return server


async def make_agent(client, demo, tool_names: list[str], **config) -> dict:
    body = {"name": "Helper", "role": "assistant", "goal": "Help", "config": {"tool_ids": [f"mcp:{demo.id}:{t}" for t in tool_names], **config}}
    r = await client.post("/api/v1/builder/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def start(client, agent, text="do it") -> str:
    r = await client.post(f"/api/v1/builder/agents/{agent['id']}/runs", json={"input": text})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued"
    return r.json()["id"]


async def get_run(client, run_id) -> dict:
    return (await client.get(f"/api/v1/builder/runs/{run_id}")).json()


def worker(runtime, name="w1") -> Worker:
    return Worker(queue=runtime["queue"], worker_id=name, concurrency=2)


async def kill(w: Worker, db, run_id: str) -> None:
    """Simulate the worker process dying: tasks gone, lease still held, then lapsed."""
    await w.stop()
    await db.execute(update(BuilderRun).where(BuilderRun.id == run_id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()


# ── Happy path ───────────────────────────────────────────────────────────────


async def test_agent_calls_a_tool_and_answers(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gw = gateway([reply(calls=[("demo__echo", {"text": "namaste"})]), reply("The tool said namaste.")])
    run_id = await start(tenant_client, agent, "say namaste")
    await worker(runtime).drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded", run
    assert run["output_text"] == "The tool said namaste."
    assert (run["prompt_tokens"], run["completion_tokens"]) == (20, 10)
    assert [(c["tool_name"], c["status"], c["risk"]) for c in run["tool_calls"]] == [("echo", "succeeded", "read")]
    assert [m["role"] for m in run["nodes"][0]["transcript"]] == ["user", "assistant", "tool", "assistant"]
    # The model saw the tool definitions, then the tool's result.
    assert [t.name for t in gw.requests[0].tools] == ["demo__echo"]
    assert gw.requests[1].messages[-1].content == "namaste"
    assert "Helper" in gw.requests[0].messages[0].content


async def test_preflight_blocks_a_run_that_cannot_work(db, tenant_client, demo, tenant_user):
    agent = await make_agent(tenant_client, demo, ["echo"])
    await mcp_auth.delete_user_credential(db, server_id=demo.id, user_id=tenant_user.id)
    await db.commit()
    r = await tenant_client.post(f"/api/v1/builder/agents/{agent['id']}/runs", json={"input": "x"})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "not_connected"
    assert (await db.execute(select(BuilderRun))).scalars().first() is None


async def test_runs_are_private_to_whoever_started_them(tenant_client, make_user_client, demo, gateway, runtime, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("hi")])
    run_id = await start(tenant_client, agent)
    colleague = await make_user_client(CurrentUser(id="tu_2", email="c@x.io", full_name="C", role="tenant_admin", tenant_id=tenant.id))
    assert (await colleague.get(f"/api/v1/builder/runs/{run_id}")).status_code == 404
    assert (await colleague.get("/api/v1/builder/runs")).json() == []


# ── Approvals ────────────────────────────────────────────────────────────────


async def test_data_changing_call_waits_for_approval(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    gateway([reply(calls=[("demo__send_note", {"text": "hello"})]), reply("Sent.")])
    run_id = await start(tenant_client, agent)
    w = worker(runtime)
    await w.drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "waiting"
    assert not runtime["notes"].exists()  # nothing ran yet
    [approval] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert (approval["kind"], approval["risk"], approval["payload"]["arguments"]) == ("tool_call", "edit", {"text": "hello"})

    r = await tenant_client.post(f"/api/v1/builder/approvals/{approval['id']}", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert (await get_run(tenant_client, run_id))["status"] == "queued"
    await w.drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Sent."
    assert runtime["notes"].read_text() == "hello\n"
    assert run["recoveries"] == 0  # resuming after an approval isn't a crash


async def test_rejected_call_is_reported_to_the_model(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    gw = gateway([reply(calls=[("demo__send_note", {"text": "hello"})]), reply("OK, I didn't send it.")])
    run_id = await start(tenant_client, agent)
    w = worker(runtime)
    await w.drain()
    [approval] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    await tenant_client.post(f"/api/v1/builder/approvals/{approval['id']}", json={"decision": "reject"})
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and not runtime["notes"].exists()
    assert run["tool_calls"][0]["status"] == "declined"
    assert "declined" in gw.requests[-1].messages[-1].content


async def test_edited_arguments_are_validated_and_used(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    gateway([reply(calls=[("demo__send_note", {"text": "draft"})]), reply("Done.")])
    run_id = await start(tenant_client, agent)
    w = worker(runtime)
    await w.drain()
    [approval] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    url = f"/api/v1/builder/approvals/{approval['id']}"
    r = await tenant_client.post(url, json={"decision": "edit", "arguments": {"text": 5}})
    assert r.status_code == 422 and r.json()["errors"]
    r = await tenant_client.post(url, json={"decision": "edit", "arguments": {"text": "final"}})
    assert r.json()["status"] == "edited"
    await w.drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    assert runtime["notes"].read_text() == "final\n"


async def test_approval_policy_can_allow_writes(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"], approvals={"read": False, "edit": False, "delete": True})
    gateway([reply(calls=[("demo__send_note", {"text": "auto"})]), reply("Done.")])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    assert runtime["notes"].read_text() == "auto\n"


async def test_cancel_a_waiting_run(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    gateway([reply(calls=[("demo__send_note", {"text": "x"})])])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    [approval] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert (await tenant_client.post(f"/api/v1/builder/runs/{run_id}/cancel")).json()["status"] == "cancelled"
    assert (await tenant_client.post(f"/api/v1/builder/runs/{run_id}/cancel")).status_code == 409
    r = await tenant_client.post(f"/api/v1/builder/approvals/{approval['id']}", json={"decision": "approve"})
    assert r.status_code == 409
    assert (await tenant_client.get("/api/v1/builder/approvals")).json() == []


# ── Crash recovery ───────────────────────────────────────────────────────────


async def test_crash_between_model_turns_resumes_without_repeating_a_write(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"], approvals={"read": False, "edit": False, "delete": True})
    gw = gateway([reply(calls=[("demo__send_note", {"text": "once"})]), HANG, reply("All done.")])
    run_id = await start(tenant_client, agent)

    w1 = worker(runtime, "w1")
    await w1.start(reaper=False)
    await asyncio.wait_for(gw.hung.wait(), 30)  # tool already ran; second model call stuck
    await kill(w1, db, run_id)
    assert runtime["notes"].read_text() == "once\n"

    w2 = worker(runtime, "w2")
    assert await w2.reap() == 1
    await w2.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "All done."
    assert run["recoveries"] == 1
    assert runtime["notes"].read_text() == "once\n"  # not sent twice
    assert len(run["tool_calls"]) == 1


async def test_crash_during_a_write_call_asks_before_running_it_again(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["post_slowly"], approvals={"read": False, "edit": False, "delete": True})
    gw = gateway([reply(calls=[("demo__post_slowly", {"text": "maybe", "seconds": 30})]), reply("Finished.")])
    events: list[dict] = []
    run_id = await start(tenant_client, agent)

    async with runtime["bus"].subscribe(run_id) as sub:
        w1 = worker(runtime, "w1")
        await w1.start(reaper=False)
        while True:
            event = await asyncio.wait_for(sub.get(timeout=30), 30)
            events.append(event)
            if event["type"] == "tool_call" and event["phase"] == "started":
                break
        for _ in range(100):  # the server wrote the note, then sleeps
            if runtime["notes"].exists():
                break
            await asyncio.sleep(0.1)
        await kill(w1, db, run_id)

    w2 = worker(runtime, "w2")
    await w2.reap()
    await w2.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "waiting"
    [approval] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert approval["kind"] == "uncertain_call" and "may already have run" in approval["payload"]["message"]

    # The person says it already went through: don't run it again.
    await tenant_client.post(f"/api/v1/builder/approvals/{approval['id']}", json={"decision": "reject"})
    await w2.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Finished."
    assert runtime["notes"].read_text() == "maybe\n"
    assert "Not run again" in gw.requests[-1].messages[-1].content


async def test_crash_during_a_read_call_just_runs_it_again(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["wait_for"])
    gateway([reply(calls=[("demo__wait_for", {"seconds": 30})]), reply("Waited.")])
    run_id = await start(tenant_client, agent)
    async with runtime["bus"].subscribe(run_id) as sub:
        w1 = worker(runtime, "w1")
        await w1.start(reaper=False)
        while (await asyncio.wait_for(sub.get(timeout=30), 30)).get("phase") != "started":
            pass
        await kill(w1, db, run_id)
    await db.execute(update(BuilderToolCall).values(arguments={"seconds": 0}))  # keep the re-run fast
    await db.commit()
    w2 = worker(runtime, "w2")
    await w2.reap()
    await w2.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["approvals"] == []


async def test_a_run_that_keeps_crashing_is_failed(db, tenant_client, demo, gateway, runtime, monkeypatch):
    monkeypatch.setattr(get_builder_settings(), "RUN_MAX_ATTEMPTS", 1)
    agent = await make_agent(tenant_client, demo, ["echo"])
    gw = gateway([HANG, HANG])
    run_id = await start(tenant_client, agent)
    for name in ("w1", "w2"):
        w = worker(runtime, name)
        await w.start(reaper=False)
        if name == "w2":
            await w.reap()
        await asyncio.wait_for(gw.hung.wait(), 30)
        gw.hung.clear()
        await kill(w, db, run_id)
    w3 = worker(runtime, "w3")
    await w3.reap()
    await w3.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "failed" and "interrupted" in run["error"]


async def test_a_worker_that_loses_its_lease_stops(db, tenant_client, demo, gateway, runtime, monkeypatch):
    monkeypatch.setattr(get_builder_settings(), "RUN_HEARTBEAT_SECONDS", 0.05)
    agent = await make_agent(tenant_client, demo, ["echo"])
    gw = gateway([HANG])
    run_id = await start(tenant_client, agent)
    w1 = worker(runtime, "w1")
    await w1.start(reaper=False)
    await asyncio.wait_for(gw.hung.wait(), 30)
    await db.execute(update(BuilderRun).where(BuilderRun.id == run_id).values(lease_owner="someone-else"))
    await db.commit()
    for _ in range(100):
        if not w1._active:
            break
        await asyncio.sleep(0.05)
    assert not w1._active  # execution cancelled, nothing finalised by w1
    run = (await db.execute(select(BuilderRun).where(BuilderRun.id == run_id))).scalars().one()
    await db.refresh(run)
    assert run.status == "running" and run.lease_owner == "someone-else"
    await w1.stop()


async def test_reaper_requeues_a_waiting_run_whose_decision_raced_the_pause(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    gateway([reply(calls=[("demo__send_note", {"text": "x"})]), reply("ok")])
    run_id = await start(tenant_client, agent)
    w = worker(runtime)
    await w.drain()
    # Decided without the API's re-queue (as if it landed mid-pause).
    await db.execute(update(BuilderApproval).values(status=states.APPROVAL_APPROVED))
    await db.commit()
    assert await w.reap() == 1
    await w.drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"


# ── Model behaviour ──────────────────────────────────────────────────────────


async def test_model_errors_are_retried_then_fail_the_run(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"], reliability={"retries": 1})
    gw = gateway([RuntimeError("503 Service Unavailable"), RuntimeError("503 Service Unavailable")])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "failed" and "model request failed" in run["error"]
    assert len(gw.requests) == 2


async def test_tool_budget_forces_an_answer(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"], tools={"max_calls": 1})
    gw = gateway([reply(calls=[("demo__echo", {"text": "a"})]), reply("Answer from what I have.")])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["output_text"] == "Answer from what I have."
    assert gw.requests[1].tools is None
    assert "used all the tool calls" in gw.requests[1].messages[-1].content


async def test_bad_tool_call_is_explained_to_the_model(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gw = gateway([reply(calls=[("demo__echo", {"text": 5}), ("nope", {})]), reply("Fixed.")])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    tool_messages = [m.content for m in gw.requests[1].messages if m.role.value == "tool"]
    assert "don't match" in tool_messages[0] and "no tool named nope" in tool_messages[1]


async def test_knowledge_base_search(db, tenant_client, demo, gateway, runtime, monkeypatch, tenant):
    from knowledge.models import KnowledgeBase

    kb = KnowledgeBase(tenant_id=tenant.id, owner_id="tu_1", name="Policies")
    db.add(kb)
    await db.commit()

    async def fake_retrieve(db, *, knowledge_base_id, tenant_id, query, k):
        assert (knowledge_base_id, tenant_id) == (kb.id, tenant.id)
        return [{"content": "Refunds within 30 days.", "filename": "policy.pdf", "score": 0.9}]

    monkeypatch.setattr("knowledge.services.retrieval.retrieve", fake_retrieve)
    agent = await make_agent(tenant_client, demo, [], knowledge_base_ids=[kb.id])
    gw = gateway([reply(calls=[("search_knowledge", {"query": "refund window"})]), reply("30 days [policy.pdf].")])
    run_id = await start(tenant_client, agent)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output"]["sources"] == ["policy.pdf"]
    assert "Refunds within 30 days." in gw.requests[1].messages[-1].content


# ── Events ───────────────────────────────────────────────────────────────────


async def test_live_events_and_websocket_stream(tenant_client, demo, gateway, runtime):
    from builder.api.v1.runs import stream_run_events

    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply(calls=[("demo__echo", {"text": "x"})]), reply("done")])
    run_id = await start(tenant_client, agent)

    class FakeSocket:
        def __init__(self):
            self.sent: list[dict] = []

        async def send_json(self, data, mode="text"):
            self.sent.append(data)

    socket_ = FakeSocket()
    streaming = asyncio.create_task(stream_run_events(socket_, run_id, idle_seconds=0.2))
    await asyncio.sleep(0.1)
    await worker(runtime).drain()
    await asyncio.wait_for(streaming, 10)

    types = [m["type"] for m in socket_.sent]
    assert types[0] == "snapshot" and types[-1] == "snapshot"
    assert {"run_status", "agent_turn", "tool_call", "output"} <= set(types)
    assert socket_.sent[-1]["run"]["status"] == "succeeded"
    phases = [m.get("phase") for m in socket_.sent if m["type"] == "tool_call"]
    assert phases == ["started", "finished"]


async def test_websocket_token_check():
    from builder.api.v1.runs import websocket_user

    assert await websocket_user("not-a-jwt") is None
