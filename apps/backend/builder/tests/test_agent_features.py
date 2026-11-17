"""Memory, cost, sub-agents, attachments, export/import, what an agent needs,
webhooks and chat starters — each end to end through the API and the worker
(scripted model, the real demo MCP server)."""
from __future__ import annotations

import io
from urllib.parse import urlsplit

from sqlalchemy import select

from apps.llm_gateway.types import CompletionResponse, TokenUsage
from builder.models import BuilderRun
from builder.pricing import estimate_cost_usd, rates_for
from builder.tests.test_runs import demo, gateway, get_run, make_agent, reply, runtime, start, worker  # noqa: F401 — fixtures

B = "/api/v1/builder"


async def make_named(client, name: str, **config) -> dict:
    r = await client.post(f"{B}/agents", json={"name": name, "role": "assistant", "goal": f"{name}'s goal", "config": config})
    assert r.status_code == 201, r.text
    return r.json()


def tool_names(request) -> list[str]:
    return [t.name for t in request.tools or []]


# ── Memory ───────────────────────────────────────────────────────────────────


async def test_memory_is_saved_and_given_back_in_later_runs(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [], memory={"enabled": True})
    gw = gateway([reply(calls=[("remember", {"fact": "Prefers answers in Hindi"})]), reply("Noted."), reply("Namaste")])

    first = await start(tenant_client, agent, "Please answer me in Hindi from now on")
    await worker(runtime).drain()
    assert "remember" in tool_names(gw.requests[0])
    [memory] = (await tenant_client.get(f"{B}/agents/{agent['id']}/memories")).json()
    assert (memory["content"], memory["source_run_id"]) == ("Prefers answers in Hindi", first)

    await start(tenant_client, agent, "hello")
    await worker(runtime).drain()
    assert "Prefers answers in Hindi" in gw.requests[2].messages[0].content


async def test_memory_api_and_off_by_default(tenant_client, demo, gateway, runtime):
    plain = await make_agent(tenant_client, demo, [])
    gw = gateway([reply("hi")])
    await start(tenant_client, plain)
    await worker(runtime).drain()
    assert "remember" not in tool_names(gw.requests[0])

    agent = await make_agent(tenant_client, demo, [], memory={"enabled": True, "max_items": 5})
    url = f"{B}/agents/{agent['id']}/memories"
    r = await tenant_client.post(url, json={"content": "Works on payments"})
    assert r.status_code == 201
    assert (await tenant_client.post(url, json={"content": "works on payments."})).status_code == 409
    for i in range(6):
        assert (await tenant_client.post(url, json={"content": f"fact {i}"})).status_code == 201
    assert len((await tenant_client.get(url)).json()) == 5  # the oldest went
    one = (await tenant_client.get(url)).json()[0]
    assert (await tenant_client.delete(f"{url}/{one['id']}")).status_code == 204
    assert len((await tenant_client.get(url)).json()) == 4
    assert (await tenant_client.delete(url)).status_code == 204
    assert (await tenant_client.get(url)).json() == []


async def test_memory_is_private_to_each_person(tenant_client, make_user_client, demo, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, [], memory={"enabled": True})
    await tenant_client.post(f"{B}/agents/{agent['id']}/memories", json={"content": "My secret project"})
    colleague = await make_user_client(CurrentUser(id="tu_2", email="c@x.io", full_name="C", role="tenant_admin", tenant_id=tenant.id))
    assert (await colleague.get(f"{B}/agents/{agent['id']}/memories")).json() == []


# ── Cost ─────────────────────────────────────────────────────────────────────


def test_prices_match_dated_and_prefixed_model_names():
    assert rates_for("azure/gpt-4o-2024-08-06") == rates_for("gpt-4o")
    assert rates_for("gpt-4o-mini-2024-07-18") == rates_for("gpt-4o-mini")
    assert rates_for("some-unknown-model") is None
    assert estimate_cost_usd("gpt-4o", 1000, 1000) == 0.0125
    assert estimate_cost_usd(None, 10, 10) is None


async def test_a_run_records_its_cost_and_usage_adds_it_up(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    priced = CompletionResponse(content="hi", usage=TokenUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000), model="gpt-4o-2024-08-06")
    gateway([priced, reply("unpriced")])
    first = await start(tenant_client, agent)
    await worker(runtime).drain()
    assert (await get_run(tenant_client, first))["cost_usd"] == 0.0125
    await start(tenant_client, agent)
    await worker(runtime).drain()

    usage = (await tenant_client.get(f"{B}/agents/{agent['id']}/usage", params={"days": 7})).json()
    assert (usage["scope"], usage["runs"], usage["succeeded"], usage["cost_usd"], usage["unpriced_runs"]) == ("everyone", 2, 2, 0.0125, 1)
    assert usage["prompt_tokens"] == 1010 and len(usage["daily"]) == 7
    assert usage["daily"][-1]["runs"] == 2


# ── Sub-agents ───────────────────────────────────────────────────────────────


async def test_an_agent_hands_a_task_to_another(tenant_client, demo, gateway, runtime):
    helper = await make_agent(tenant_client, demo, ["echo"])  # "Helper"
    lead = await make_named(tenant_client, "Lead", sub_agent_ids=[helper["id"]])
    gw = gateway([
        reply(calls=[("ask_helper", {"task": "Echo the word hi"})]),  # Lead hands over
        reply(calls=[("demo__echo", {"text": "hi"})]),  # Helper uses its own tool
        reply("Echoed: hi"),  # Helper answers
        reply("Helper says it echoed hi."),  # Lead answers
    ])
    run_id = await start(tenant_client, lead, "Get hi echoed")
    await worker(runtime).drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Helper says it echoed hi."
    assert run["prompt_tokens"] == 40  # all four model calls
    assert "ask_helper" in tool_names(gw.requests[0])
    assert gw.requests[1].messages[0].content.startswith("You are Helper")
    assert gw.requests[1].messages[-1].content == "Echo the word hi"
    assert "ask_" not in " ".join(tool_names(gw.requests[1]))  # one level only
    assert gw.requests[3].messages[-1].content == "Echoed: hi"
    assert [n["node_type"] for n in run["nodes"]] == ["agent", "sub_agent"]


async def test_a_sub_agent_waits_for_approval_and_resumes(tenant_client, demo, gateway, runtime):
    helper = await make_agent(tenant_client, demo, ["send_note"])
    lead = await make_named(tenant_client, "Lead", sub_agent_ids=[helper["id"]])
    gateway([
        reply(calls=[("ask_helper", {"task": "Note hello"})]),
        reply(calls=[("demo__send_note", {"text": "hello"})]),
        reply("Noted hello."),
        reply("Done: noted hello."),
    ])
    run_id = await start(tenant_client, lead)
    w = worker(runtime)
    await w.drain()
    assert (await get_run(tenant_client, run_id))["status"] == "waiting"
    [approval] = (await tenant_client.get(f"{B}/approvals")).json()
    await tenant_client.post(f"{B}/approvals/{approval['id']}", json={"decision": "approve"})
    await w.drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Done: noted hello."
    assert runtime["notes"].read_text() == "hello\n"  # sent once


async def test_sub_agent_rules(tenant_client, demo):
    helper = await make_agent(tenant_client, demo, [])
    r = await tenant_client.patch(f"{B}/agents/{helper['id']}", json={"config": {"sub_agent_ids": [helper["id"]]}})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "sub_agent_self"
    r = await tenant_client.post(f"{B}/agents", json={"name": "X", "role": "r", "goal": "g", "config": {"sub_agent_ids": ["nope"]}})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "sub_agent_missing"

    await make_named(tenant_client, "Lead", sub_agent_ids=[helper["id"]])
    r = await tenant_client.delete(f"{B}/agents/{helper['id']}")
    assert r.status_code == 409 and "Lead" in r.json()["detail"]


# ── Attachments ──────────────────────────────────────────────────────────────


async def upload(client, name: str, data: bytes, ctype: str) -> dict:
    r = await client.post(f"{B}/attachments", files={"file": (name, data, ctype)})
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_document_is_read_and_sent_with_the_message(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, [])
    doc = await upload(tenant_client, "notes.txt", b"The launch date is 5 November.", "text/plain")
    assert (doc["kind"], doc["chars"]) == ("document", 30)
    gw = gateway([reply("5 November.")])
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "When is the launch?", "attachment_ids": [doc["id"]]})
    assert r.status_code == 202 and r.json()["input"]["attachments"] == [{"id": doc["id"], "filename": "notes.txt", "kind": "document"}]
    await worker(runtime).drain()
    sent = gw.requests[0].messages[-1].content
    assert sent.startswith("When is the launch?") and "The launch date is 5 November." in sent and 'name="notes.txt"' in sent


async def test_an_image_goes_to_the_model_as_an_image(tenant_client, demo, gateway, runtime):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    agent = await make_agent(tenant_client, demo, [])
    img = await upload(tenant_client, "red.png", buf.getvalue(), "image/png")
    assert img["kind"] == "image"
    gw = gateway([reply("It's red.")])
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "What colour?", "attachment_ids": [img["id"]]})
    await worker(runtime).drain()
    parts = gw.requests[0].messages[-1].content
    assert parts[0] == {"type": "text", "text": "What colour?"}
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # The checkpoint keeps a reference, and the transcript names it.
    run = await get_run(tenant_client, r.json()["id"])
    assert run["nodes"][0]["transcript"][0]["content"] == "What colour?\n[image: red.png]"


async def test_attachments_are_checked(tenant_client, make_user_client, demo, tenant):
    from src.api.deps import CurrentUser

    r = await tenant_client.post(f"{B}/attachments", files={"file": ("x.exe", b"MZ...", "application/octet-stream")})
    assert r.status_code == 422
    doc = await upload(tenant_client, "a.txt", b"hello", "text/plain")
    agent = await make_agent(tenant_client, demo, [])
    colleague = await make_user_client(CurrentUser(id="tu_2", email="c@x.io", full_name="C", role="tenant_admin", tenant_id=tenant.id))
    r = await colleague.post(f"{B}/agents/{agent['id']}/runs", json={"input": "x", "attachment_ids": [doc["id"]]})
    assert r.status_code == 404  # not theirs


# ── Export / import ──────────────────────────────────────────────────────────


async def test_export_then_import_matches_tools_by_name(tenant_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"], chat={"welcome": "Hi!", "starters": ["Echo something"]})
    r = await tenant_client.get(f"{B}/agents/{agent['id']}/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    file = r.json()
    assert file["tools"] == [{"server": "demo", "tool": "echo"}] and "tool_ids" not in file["agent"]["config"]

    file["tools"].append({"server": "gmail", "tool": "send"})
    file["knowledge_bases"] = ["Policies"]
    r = await tenant_client.post(f"{B}/agents/import", json=file)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent"]["id"] != agent["id"] and body["agent"]["config"]["tool_ids"] == [f"mcp:{demo.id}:echo"]
    assert body["agent"]["config"]["chat"] == {"welcome": "Hi!", "starters": ["Echo something"], "answer_general": True}
    assert len(body["skipped"]) == 2

    assert (await tenant_client.post(f"{B}/agents/import", json={**file, "format": "other"})).status_code == 422


# ── What an agent needs ──────────────────────────────────────────────────────


async def test_an_agent_says_which_accounts_each_person_must_connect(tenant_client, make_user_client, demo, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, ["echo"])
    url = f"{B}/agents/{agent['id']}/requirements"
    mine = (await tenant_client.get(url)).json()
    assert mine == {"ready": True, "requirements": [{"server_id": demo.id, "name": "demo", "connected": True, "tools": ["echo"]}]}

    # A teammate runs it as themselves, and hasn't connected that server yet.
    colleague = await make_user_client(CurrentUser(id="tu_3", email="d@x.io", full_name="D", role="tenant_user", tenant_id=tenant.id))
    theirs = (await colleague.get(url)).json()
    assert (theirs["ready"], theirs["requirements"][0]["connected"]) == (False, False)

    bare = await make_agent(tenant_client, demo, [])
    assert (await tenant_client.get(f"{B}/agents/{bare['id']}/requirements")).json() == {"ready": True, "requirements": []}


# ── Webhooks ─────────────────────────────────────────────────────────────────


async def test_a_webhook_runs_its_agent_on_what_was_posted(tenant_client, anon_client, demo, gateway, runtime, db):
    agent = await make_agent(tenant_client, demo, [])
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/webhooks", json={"name": "Leads form", "instruction": "Qualify this lead:"})
    assert r.status_code == 201
    hook = r.json()
    path = urlsplit(hook["url"]).path
    assert path.startswith("/api/v1/public/hooks/eai_wh_")

    gw = gateway([reply("Hot lead."), reply("Second.")])
    r = await anon_client.post(path, json={"text": "Asha from Acme wants 200 seats", "channel": "web"})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()
    run = (await db.execute(select(BuilderRun).where(BuilderRun.id == r.json()["run_id"]))).scalars().one()
    assert (run.status, run.webhook_id, run.owner_id) == ("succeeded", hook["id"], "tu_1")
    assert gw.requests[0].messages[-1].content == "Qualify this lead:\n\nAsha from Acme wants 200 seats"

    # Slack-style form post, and Slack's URL check.
    r = await anon_client.post(path, data={"text": "from slack", "user_name": "asha"})
    assert r.status_code == 202
    r = await anon_client.post(path, json={"type": "url_verification", "challenge": "abc"})
    assert r.json() == {"challenge": "abc"}

    hooks = (await tenant_client.get(f"{B}/agents/{agent['id']}/webhooks")).json()
    assert hooks[0]["last_run_id"] and "url" not in hooks[0]
    await tenant_client.patch(f"{B}/webhooks/{hook['id']}", json={"enabled": False})
    assert (await anon_client.post(path, json={"text": "x"})).status_code == 403
    assert (await anon_client.post("/api/v1/public/hooks/eai_wh_wrong", json={"text": "x"})).status_code == 404


async def test_webhook_rate_limit_and_failed_checks(tenant_client, anon_client, demo, db):
    agent = await make_agent(tenant_client, demo, [])
    hook = (await tenant_client.post(f"{B}/agents/{agent['id']}/webhooks", json={"requests_per_minute": 1})).json()
    path = urlsplit(hook["url"]).path
    assert (await anon_client.post(path, json={})).status_code == 422  # nothing to work on
    assert (await anon_client.post(path, json={"text": "one"})).status_code == 202
    assert (await anon_client.post(path, json={"text": "two"})).status_code == 429


def test_payload_text_shapes():
    from builder.triggers.webhooks import payload_text

    assert payload_text(b'{"message": " hi "}', "application/json") == "hi"
    assert payload_text(b'{"name": "Asha", "seats": 200}', "application/json") == "name: Asha\nseats: 200"
    assert payload_text(b"text=hello+there&team=x", "application/x-www-form-urlencoded") == "hello there"
    assert payload_text(b"plain words", "text/plain") == "plain words"


# ── Chat starters ────────────────────────────────────────────────────────────


async def test_welcome_and_starters_are_validated(tenant_client, demo):
    agent = await make_agent(tenant_client, demo, [], chat={"welcome": "Ask me about refunds.", "starters": [" Refund status ", "Refund status", ""]})
    assert agent["config"]["chat"] == {"welcome": "Ask me about refunds.", "starters": ["Refund status"], "answer_general": True}
    r = await tenant_client.post(f"{B}/agents", json={"name": "X", "role": "r", "goal": "g", "config": {"chat": {"starters": ["a"] * 5}}})
    assert r.status_code == 422
