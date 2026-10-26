"""Playground chats: runs grouped into a conversation, earlier turns given to
the agent as context, private to whoever started them, deletable."""
from __future__ import annotations

from sqlalchemy import func, select

from builder.models import BuilderConversation, BuilderNodeRun, BuilderRun, BuilderToolCall
from builder.tests.test_runs import demo, gateway, get_run, make_agent, reply, runtime, worker  # noqa: F401 — fixtures

B = "/api/v1/builder"


async def send(client, agent, text: str, **chat) -> dict:
    r = await client.post(f"{B}/agents/{agent['id']}/runs", json={"input": text, **chat})
    assert r.status_code == 202, r.text
    return r.json()


async def test_a_chat_carries_its_earlier_turns(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gw = gateway([reply("Paris is the capital of France."), reply("About 2.1 million people.")])

    first = await send(tenant_client, agent, "What is the capital of France?", new_conversation=True)
    chat_id = first["conversation_id"]
    assert chat_id
    await worker(runtime).drain()
    second = await send(tenant_client, agent, "How many people live there?", conversation_id=chat_id)
    await worker(runtime).drain()

    # The second model call saw the first question and answer before the new one.
    roles = [(m.role.value, m.content) for m in gw.requests[1].messages[1:]]
    assert roles == [
        ("user", "What is the capital of France?"),
        ("assistant", "Paris is the capital of France."),
        ("user", "How many people live there?"),
    ]
    # The first run had no history.
    assert [m.role.value for m in gw.requests[0].messages] == ["system", "user"]

    chats = (await tenant_client.get(f"{B}/conversations", params={"agent_id": agent["id"]})).json()
    assert [(c["id"], c["title"], c["turn_count"]) for c in chats] == [(chat_id, "What is the capital of France?", 2)]
    runs = (await tenant_client.get(f"{B}/conversations/{chat_id}/runs")).json()
    assert [r["id"] for r in runs] == [first["id"], second["id"]]
    assert runs[1]["output_text"] == "About 2.1 million people." and "tool_calls" in runs[1]


async def test_one_off_runs_and_new_chats(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("a"), reply("b")])
    assert (await send(tenant_client, agent, "x"))["conversation_id"] is None
    await worker(runtime).drain()
    other = await send(tenant_client, agent, "y", new_conversation=True)
    await worker(runtime).drain()
    chats = (await tenant_client.get(f"{B}/conversations", params={"agent_id": agent["id"]})).json()
    assert [c["id"] for c in chats] == [other["conversation_id"]]


async def test_a_busy_chat_refuses_a_second_message(tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("a")])
    first = await send(tenant_client, agent, "one", new_conversation=True)
    r = await tenant_client.post(f"{B}/agents/{agent['id']}/runs", json={"input": "two", "conversation_id": first["conversation_id"]})
    assert r.status_code == 409


async def test_chats_are_private_and_bound_to_their_agent(tenant_client, make_user_client, demo, gateway, runtime, tenant):
    from src.api.deps import CurrentUser

    agent = await make_agent(tenant_client, demo, ["echo"])
    other_agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply("a")])
    chat_id = (await send(tenant_client, agent, "hello", new_conversation=True))["conversation_id"]
    await worker(runtime).drain()

    r = await tenant_client.post(f"{B}/agents/{other_agent['id']}/runs", json={"input": "x", "conversation_id": chat_id})
    assert r.status_code == 409
    colleague = await make_user_client(CurrentUser(id="tu_2", email="c@x.io", full_name="C", role="tenant_admin", tenant_id=tenant.id))
    assert (await colleague.get(f"{B}/conversations/{chat_id}")).status_code == 404
    assert (await colleague.get(f"{B}/conversations")).json() == []
    assert (await colleague.delete(f"{B}/conversations/{chat_id}")).status_code == 404
    # They can't post into it either (here preflight stops them first: their own account isn't connected).
    r = await colleague.post(f"{B}/agents/{agent['id']}/runs", json={"input": "x", "conversation_id": chat_id})
    assert r.status_code in (404, 422)


async def test_rename_and_delete_a_chat_with_its_runs(db, tenant_client, demo, gateway, runtime):
    agent = await make_agent(tenant_client, demo, ["echo"])
    gateway([reply(calls=[("demo__echo", {"text": "hi"})]), reply("done")])
    run = await send(tenant_client, agent, "echo hi", new_conversation=True)
    chat_id = run["conversation_id"]

    # Not while it's still answering.
    assert (await tenant_client.delete(f"{B}/conversations/{chat_id}")).status_code == 409
    await worker(runtime).drain()

    r = await tenant_client.patch(f"{B}/conversations/{chat_id}", json={"title": "  Greeting   test "})
    assert r.json()["title"] == "Greeting test"
    assert (await tenant_client.delete(f"{B}/conversations/{chat_id}")).status_code == 204
    assert (await tenant_client.get(f"{B}/conversations/{chat_id}")).status_code == 404
    for model in (BuilderConversation, BuilderRun, BuilderNodeRun, BuilderToolCall):
        assert (await db.execute(select(func.count()).select_from(model))).scalar_one() == 0, model
