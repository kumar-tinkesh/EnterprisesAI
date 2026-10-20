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
    assert (await visitor.get(f"{B}/approvals")).json() == []
    assert (await db.execute(select(BuilderRun.caller_user_id))).scalars().all() == ["ou_1"]
