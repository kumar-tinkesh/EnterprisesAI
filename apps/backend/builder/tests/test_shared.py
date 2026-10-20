"""Share links: a publishable key's /r/{slug}, run by anyone signed in.

Runs execute as the publisher (tu_1, ``tenant_client``); callers are other
people — another workspace's user or a solo user — who see only their own.
"""
from __future__ import annotations

from sqlalchemy import select

from src.api.deps import CurrentUser

from builder.models import BuilderRun
from builder.tests.test_publishing import publish
from builder.tests.test_runs import demo, gateway, make_agent, reply, runtime, worker  # noqa: F401  (fixtures)

B = "/api/v1/builder"
S = "/api/v1/shared"


def outsider() -> CurrentUser:
    return CurrentUser(id="ou_1", email="o@elsewhere.io", full_name="Outsider", role="tenant_user", tenant_id="tenant_other")


async def test_anyone_signed_in_runs_it_and_sees_only_their_own(db, tenant_client, solo_client, anon_client, make_user_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], share=True)
    assert key["share_enabled"] and len(key["share_slug"]) >= 12 and key["tool_mode"] == "publisher"
    slug = key["share_slug"]

    info = (await anon_client.get(f"{S}/{slug}")).json()  # the page shows what it is before signing in
    assert (info["kind"], info["name"], info["description"], info["shared_by"]) == ("agent", "Helper", "Help", "Tenant User")
    assert (await anon_client.post(f"{S}/{slug}/runs", json={"input": "hi"})).status_code == 401
    assert (await anon_client.get(f"{S}/nope")).status_code == 404

    visitor = await make_user_client(outsider())
    gateway([reply("Hi there.")])
    r = await visitor.post(f"{S}/{slug}/runs", json={"input": "say hi", "wait_seconds": 0})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()
    run_id = r.json()["run_id"]
    done = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    assert (done["status"], done["output"], done["input"]) == ("succeeded", "Hi there.", "say hi")
    assert [x["run_id"] for x in (await visitor.get(f"{S}/{slug}/runs")).json()] == [run_id]

    row = await db.get(BuilderRun, run_id)
    assert (row.owner_id, row.tenant_id, row.caller_user_id, row.purpose) == ("tu_1", "tenant_test_01", "ou_1", "public")

    # Someone else signed in sees none of it.
    assert (await solo_client.get(f"{S}/{slug}/runs/{run_id}")).status_code == 404
    assert (await solo_client.get(f"{S}/{slug}/runs")).json() == []
    assert (await solo_client.post(f"{S}/{slug}/runs/{run_id}/cancel")).status_code == 404


async def test_switches_and_the_same_link_back(db, tenant_client, solo_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"])
    assert not key["share_enabled"] and key["share_slug"] is None

    on = (await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"share": True})).json()
    slug = on["share_slug"]
    assert on["share_enabled"] and (await solo_client.get(f"{S}/{slug}")).status_code == 200

    await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"share": False})
    assert (await solo_client.get(f"{S}/{slug}")).status_code == 404
    back = (await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"share": True})).json()
    assert back["share_slug"] == slug  # turning it back on keeps the link people already have

    await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"status": "paused"})
    r = await solo_client.post(f"{S}/{slug}/runs", json={"input": "x"})
    assert r.status_code == 403 and "paused" in r.json()["detail"]
    await tenant_client.delete(f"{B}/public-keys/{key['id']}")
    assert (await solo_client.get(f"{S}/{slug}")).status_code == 404


async def test_each_person_has_their_own_daily_limit(db, tenant_client, solo_client, make_user_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], share=True, per_user_daily_limit=1)
    slug = key["share_slug"]
    assert (await solo_client.get(f"{S}/{slug}")).json()["per_user_daily_limit"] == 1

    assert (await solo_client.post(f"{S}/{slug}/runs", json={"input": "one", "wait_seconds": 0})).status_code == 202
    r = await solo_client.post(f"{S}/{slug}/runs", json={"input": "two", "wait_seconds": 0})
    assert r.status_code == 429 and "your 1 runs" in r.json()["detail"]
    visitor = await make_user_client(outsider())
    assert (await visitor.post(f"{S}/{slug}/runs", json={"input": "one", "wait_seconds": 0})).status_code == 202

    off = (await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"no_per_user_limit": True})).json()
    assert off["per_user_daily_limit"] is None
    assert (await solo_client.post(f"{S}/{slug}/runs", json={"input": "two", "wait_seconds": 0})).status_code == 202


async def test_the_publisher_approves_what_their_tools_would_change(db, tenant_client, make_user_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["send_note"])
    key = await publish(tenant_client, "agents", agent["id"], share=True, acknowledge_write_tools=True)
    visitor = await make_user_client(outsider())
    gateway([reply(calls=[("demo__send_note", {"text": "hi"})]), reply("Saved.")])
    r = await visitor.post(f"{S}/{key['share_slug']}/runs", json={"input": "save hi", "wait_seconds": 0})
    await worker(runtime).drain()

    waiting = (await visitor.get(f"{S}/{key['share_slug']}/runs/{r.json()['run_id']}")).json()
    assert (waiting["status"], waiting["waiting_for"]) == ("waiting", "approval")
    [approval] = (await tenant_client.get(f"{B}/approvals")).json()  # theirs to decide, not the visitor's
    assert approval["payload"]["arguments"] == {"text": "hi"}
    assert approval["caller"] == {"id": "ou_1", "name": "", "email": ""}  # no account row in this test: the id still says whose
    detail = (await tenant_client.get(f"{B}/runs/{r.json()['run_id']}")).json()
    assert detail["caller"]["id"] == "ou_1" and detail["approvals"][0]["caller"]["id"] == "ou_1"
    assert (await visitor.get(f"{B}/approvals")).json() == []
    assert (await db.execute(select(BuilderRun.caller_user_id))).scalars().all() == ["ou_1"]


async def test_the_publisher_sees_who_used_it_and_can_block_them(db, tenant_client, solo_client, make_user_client, demo, gateway, runtime):
    from src.models import User

    db.add(User(id="solo_1", tenant_id="tenant_test_01", email="solo@x.io", full_name="Solo User", role="solo_user", hashed_password="x"))
    await db.commit()
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], share=True)
    slug = key["share_slug"]
    visitor = await make_user_client(outsider())

    gateway([reply("One."), reply("Two."), reply("Three.")])
    for client, text in ((solo_client, "a"), (solo_client, "b"), (visitor, "c")):
        assert (await client.post(f"{S}/{slug}/runs", json={"input": text, "wait_seconds": 0})).status_code == 202
    await worker(runtime).drain()

    callers = (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers")).json()
    by_id = {c["user_id"]: c for c in callers}
    assert set(by_id) == {"solo_1", "ou_1"}
    solo = by_id["solo_1"]
    assert (solo["name"], solo["email"], solo["runs"], solo["runs_today"], solo["succeeded"], solo["blocked"]) == ("Solo User", "solo@x.io", 2, 2, 2, False)
    runs = (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers/solo_1/runs")).json()
    assert sorted(r["input"]["text"] for r in runs) == ["a", "b"] and runs[0]["caller"]["email"] == "solo@x.io"
    keys = (await tenant_client.get(f"{B}/agents/{agent['id']}/public-keys")).json()
    assert keys[0]["people"] == 2
    assert (await tenant_client.get(f"{B}/published")).json()["stats"]["people"] == 2

    # Only its publisher (or a tenant admin) sees any of this.
    assert (await visitor.get(f"{B}/public-keys/{key['id']}/callers")).status_code in (403, 404)

    assert (await tenant_client.put(f"{B}/public-keys/{key['id']}/callers/solo_1/block")).status_code == 204
    r = await solo_client.post(f"{S}/{slug}/runs", json={"input": "d", "wait_seconds": 0})
    assert r.status_code == 403 and "turned off your access" in r.json()["detail"]
    assert len((await solo_client.get(f"{S}/{slug}/runs")).json()) == 2  # their earlier runs stay theirs to see
    assert (await visitor.post(f"{S}/{slug}/runs", json={"input": "e", "wait_seconds": 0})).status_code == 202
    assert {c["user_id"]: c["blocked"] for c in (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers")).json()}["solo_1"] is True
    assert (await tenant_client.put(f"{B}/public-keys/{key['id']}/callers/tu_1/block")).status_code == 422

    assert (await tenant_client.delete(f"{B}/public-keys/{key['id']}/callers/solo_1/block")).status_code == 204
    assert (await solo_client.post(f"{S}/{slug}/runs", json={"input": "f", "wait_seconds": 0})).status_code == 202


# ── Visitor links: their own tools, their own approvals ──────────────────────


async def visitor_account(db) -> None:
    """ou_1 as a real account in their own workspace (a visitor-link run executes as them)."""
    from src.models import Tenant, User

    db.add(Tenant(id="tenant_other", name="Other", slug="other", status="active", is_personal=True))
    db.add(User(id="ou_1", tenant_id="tenant_other", email="o@elsewhere.io", full_name="Outsider", role="tenant_user"))
    await db.commit()


async def test_a_visitor_link_runs_with_their_own_tools_and_approvals(db, tenant_client, make_user_client, demo, gateway, runtime):
    from vendor.services import mcp_auth

    await visitor_account(db)
    agent = await make_agent(tenant_client, demo, ["send_note"])
    key = await publish(tenant_client, "agents", agent["id"], share=True, tool_mode="visitor", acknowledge_write_tools=True)
    slug = key["share_slug"]
    assert key["tool_mode"] == "visitor"
    visitor = await make_user_client(outsider())
    assert (await visitor.get(f"{S}/{slug}")).json()["tool_mode"] == "visitor"

    # Not connected yet: the page offers Connect, and a run can't start.
    needs = (await visitor.get(f"{S}/{slug}/needs")).json()
    assert [(n["system"], n["status"], n["server_id"]) for n in needs["systems"]] == [("demo", "not_connected", demo.id)]
    assert needs["problems"] == ["Connect your demo account first."]
    r = await visitor.post(f"{S}/{slug}/runs", json={"input": "save mine"})
    assert r.status_code == 422 and r.json()["problems"] == ["Connect your demo account first."]

    await mcp_auth.store_server_credentials(db, server_id=demo.id, credentials={}, tenant_id="tenant_other", user_id="ou_1")
    await db.commit()
    needs = (await visitor.get(f"{S}/{slug}/needs")).json()
    assert needs["systems"][0]["status"] == "ready" and needs["problems"] == []

    gateway([reply(calls=[("demo__send_note", {"text": "mine"})]), reply("Saved.")])
    r = await visitor.post(f"{S}/{slug}/runs", json={"input": "save mine", "wait_seconds": 0})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()
    run_id = r.json()["run_id"]
    row = await db.get(BuilderRun, run_id)
    assert (row.owner_id, row.tenant_id, row.caller_user_id) == ("ou_1", "tenant_other", "ou_1")

    # Their tools, so their decision — shown on the link page, none of it the publisher's.
    waiting = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    assert waiting["waiting_for"] == "approval"
    [approval] = waiting["approvals"]
    assert approval["payload"]["arguments"] == {"text": "mine"}
    assert (await tenant_client.get(f"{B}/approvals")).json() == []
    assert (await tenant_client.get(f"{B}/runs/{run_id}")).status_code == 404
    assert (await visitor.post(f"{B}/approvals/{approval['id']}", json={"decision": "approve"})).status_code == 200
    await worker(runtime).drain()

    done = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    assert (done["status"], done["output"], done["approvals"]) == ("succeeded", "Saved.", [])
    homes = runtime["notes"].parent.parent
    assert "mine" in (homes / "ou_1" / "notes.txt").read_text() and not runtime["notes"].exists()

    # The publisher sees that they used it, not what they asked or got.
    [caller] = (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers")).json()
    assert (caller["user_id"], caller["runs"], caller["private_runs"], caller["waiting"]) == ("ou_1", 1, 1, 0)
    assert (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers/ou_1/runs")).json() == []


async def test_a_visitor_run_searches_the_publishers_knowledge(db, tenant_client, make_user_client, demo, gateway, runtime, monkeypatch, tenant):
    from knowledge.models import KnowledgeBase

    await visitor_account(db)
    kb = KnowledgeBase(tenant_id=tenant.id, owner_id="tu_1", name="Policies")
    db.add(kb)
    await db.commit()
    searched: list[str] = []

    async def fake_retrieve(db, *, knowledge_base_id, tenant_id, query, k):
        searched.append(tenant_id)
        return [{"content": "Refunds within 30 days.", "filename": "policy.pdf", "score": 0.9}]

    monkeypatch.setattr("knowledge.services.retrieval.retrieve", fake_retrieve)
    agent = await make_agent(tenant_client, demo, [], knowledge_base_ids=[kb.id])
    key = await publish(tenant_client, "agents", agent["id"], share=True, tool_mode="visitor")
    visitor = await make_user_client(outsider())
    assert (await visitor.get(f"{S}/{key['share_slug']}/needs")).json() == {"tool_mode": "visitor", "systems": [], "problems": []}

    gateway([reply(calls=[("search_knowledge", {"query": "refund window"})]), reply("30 days [policy.pdf].")])
    r = await visitor.post(f"{S}/{key['share_slug']}/runs", json={"input": "refunds?", "wait_seconds": 0})
    await worker(runtime).drain()
    done = (await visitor.get(f"{S}/{key['share_slug']}/runs/{r.json()['run_id']}")).json()
    assert done["status"] == "succeeded" and done["sources"] == ["policy.pdf"]
    assert searched == [tenant.id]  # the agent's knowledge, in the publisher's workspace


async def test_a_visitor_link_needs_a_workspace_account(db, tenant_client, make_user_client, demo):
    agent = await make_agent(tenant_client, demo, ["echo"])
    key = await publish(tenant_client, "agents", agent["id"], share=True, tool_mode="visitor")
    no_workspace = await make_user_client(CurrentUser(id="va_9", email="v@x.io", full_name="V", role="vendor_admin"))
    assert (await no_workspace.get(f"{S}/{key['share_slug']}/needs")).json()["problems"][0].startswith("This link uses your own")
    assert (await no_workspace.post(f"{S}/{key['share_slug']}/runs", json={"input": "x"})).status_code == 403

    # Switching a link back to the publisher's tools works the Phase-1 way.
    back = (await tenant_client.patch(f"{B}/public-keys/{key['id']}", json={"tool_mode": "publisher"})).json()
    assert back["tool_mode"] == "publisher"
    assert (await no_workspace.get(f"{S}/{key['share_slug']}/needs")).json() == {"tool_mode": "publisher", "systems": [], "problems": []}


# ── Mixed links: some apps the publisher's, the rest the visitor's ───────────


async def second_server(db, name="demo2"):
    """Another real demo MCP server — the one the visitor connects with their own account."""
    import sys

    from vendor.models import VendorMCPServer
    from vendor.services import mcp_service

    from builder.tests.test_runs import FIXTURE

    server = VendorMCPServer(
        name=name, description=name, is_global=True, transport="stdio", auth_type="env",
        auth_config={}, command=sys.executable, args=[str(FIXTURE)],
    )
    db.add(server)
    await db.flush()
    await mcp_service.test_mcp_connection(db, server=server)
    await db.commit()
    return server


async def test_a_mixed_link_asks_each_account_owner(db, tenant_client, make_user_client, demo, gateway, runtime):
    from vendor.services import mcp_auth

    await visitor_account(db)
    theirs = await second_server(db)
    body = {"name": "Helper", "role": "assistant", "goal": "Help",
            "config": {"tool_ids": [f"mcp:{demo.id}:send_note", f"mcp:{theirs.id}:send_note"]}}
    agent = (await tenant_client.post(f"{B}/agents", json=body)).json()
    check = (await tenant_client.get(f"{B}/agents/{agent['id']}/publish-check")).json()
    assert {s["server_id"] for s in check["systems"]} == {demo.id, theirs.id}  # what the publisher picks from

    key = await publish(tenant_client, "agents", agent["id"], share=True, tool_mode="mixed",
                        publisher_server_ids=[demo.id], acknowledge_write_tools=True)
    assert (key["tool_mode"], key["publisher_server_ids"]) == ("mixed", [demo.id])
    slug = key["share_slug"]
    visitor = await make_user_client(outsider())

    needs = (await visitor.get(f"{S}/{slug}/needs")).json()
    assert {(n["system"], n["owner"], n["status"]) for n in needs["systems"]} == {("demo", "publisher", "ready"), ("demo2", "you", "not_connected")}
    assert needs["problems"] == ["Connect your demo2 account first."]
    await mcp_auth.store_server_credentials(db, server_id=theirs.id, credentials={}, tenant_id="tenant_other", user_id="ou_1")
    await db.commit()
    assert (await visitor.get(f"{S}/{slug}/needs")).json()["problems"] == []

    gateway([
        reply(calls=[("demo__send_note", {"text": "for the publisher"})]),
        reply(calls=[("demo2__send_note", {"text": "for the visitor"})]),
        reply("Done."),
    ])
    r = await visitor.post(f"{S}/{slug}/runs", json={"input": "save both", "wait_seconds": 0})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    await worker(runtime).drain()

    # The publisher's app: their approval, not the visitor's.
    view = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    assert (view["waiting_for"], view["approvals"]) == ("approval", [])
    [caller] = (await tenant_client.get(f"{B}/public-keys/{key['id']}/callers")).json()
    assert (caller["waiting"], caller["private_runs"]) == (1, 1)  # it's held up on the publisher, though the run is the visitor's
    [theirs_to_decide] = (await tenant_client.get(f"{B}/approvals")).json()
    assert theirs_to_decide["payload"]["server_name"] == "demo" and theirs_to_decide["caller"]["id"] == "ou_1"
    assert (await tenant_client.post(f"{B}/approvals/{theirs_to_decide['id']}", json={"decision": "approve"})).status_code == 200
    await worker(runtime).drain()

    # The visitor's app: their approval.
    view = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    [mine] = view["approvals"]
    assert mine["payload"]["server_name"] == "demo2"
    assert (await tenant_client.get(f"{B}/approvals")).json() == []
    assert (await visitor.post(f"{B}/approvals/{mine['id']}", json={"decision": "approve"})).status_code == 200
    await worker(runtime).drain()

    done = (await visitor.get(f"{S}/{slug}/runs/{run_id}")).json()
    assert (done["status"], done["output"]) == ("succeeded", "Done.")
    homes = runtime["notes"].parent.parent
    assert "for the publisher" in runtime["notes"].read_text() and "for the visitor" not in runtime["notes"].read_text()
    assert "for the visitor" in (homes / "ou_1" / "notes.txt").read_text()
    row = await db.get(BuilderRun, run_id)
    assert (row.owner_id, row.definition["tool_owners"]) == ("ou_1", {demo.id: "tu_1"})


async def test_a_mixed_link_says_whose_connection_is_missing_and_stops_without_them(db, tenant_client, make_user_client, demo, gateway, runtime):
    from src.models import User

    await visitor_account(db)
    other = await second_server(db, "demo3")  # the publisher never connected this one
    agent = (await tenant_client.post(f"{B}/agents", json={
        "name": "Helper", "role": "assistant", "goal": "Help", "config": {"tool_ids": [f"mcp:{other.id}:echo"]},
    })).json()
    key = await publish(tenant_client, "agents", agent["id"], share=True, tool_mode="mixed", publisher_server_ids=[other.id])
    visitor = await make_user_client(outsider())
    assert (await visitor.get(f"{S}/{key['share_slug']}/needs")).json()["problems"] == ["Whoever shared this hasn't connected demo3 yet."]

    # Their account goes away between starting a run and it running: it stops, it never falls back to the visitor's.
    echo = await make_agent(tenant_client, demo, ["echo"])
    k2 = await publish(tenant_client, "agents", echo["id"], share=True, tool_mode="mixed", publisher_server_ids=[demo.id])
    gateway([reply(calls=[("demo__echo", {"text": "x"})]), reply("x")])
    r = await visitor.post(f"{S}/{k2['share_slug']}/runs", json={"input": "echo", "wait_seconds": 0})
    assert r.status_code == 202, r.text
    publisher_row = await db.get(User, "tu_1")
    publisher_row.is_active = False
    await db.commit()
    await worker(runtime).drain()
    row = await db.get(BuilderRun, r.json()["run_id"])
    await db.refresh(row)
    assert row.status == "failed" and "no longer has access" in row.error
