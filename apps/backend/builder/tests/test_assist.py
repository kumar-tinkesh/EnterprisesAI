"""Builder assistant: drafting agents/workflows, editing by instruction, tool search.

Tool matching uses the REAL hybrid search over a small catalog (lexical mode:
no embedding provider in tests); the model is a fake that answers each kind
of prompt from what the prompt itself contains.
"""
from __future__ import annotations

import json
import re

import pytest
import pytest_asyncio

from apps.llm_gateway.types import CompletionResponse, TokenUsage
from builder.models import BuilderAgent
from user.services import catalog_engine
from vendor.models import MCPTool, VendorMCPServer

WF = "/api/v1/builder/workflows"


class PromptGateway:
    """Answers by prompt kind; ``handlers`` map a marker to fn(prompt) -> dict | str."""

    def __init__(self):
        self.handlers: list[tuple[str, object]] = []
        self.prompts: list[str] = []

    def on(self, marker: str, handler):
        self.handlers.append((marker, handler))
        return self

    def seen(self, marker: str) -> list[str]:
        return [p for p in self.prompts if marker in p]

    async def complete(self, request, provider=None, fallback=True):
        prompt = request.messages[0].content
        self.prompts.append(prompt)
        for marker, handler in self.handlers:
            if marker in prompt:
                out = handler(prompt) if callable(handler) else handler
                if isinstance(out, list):  # a queue of answers
                    out = out.pop(0) if len(out) > 1 else out[0]
                text = out if isinstance(out, str) else json.dumps(out)
                return CompletionResponse(content=text, usage=TokenUsage(10, 5, 15))
        raise AssertionError(f"unexpected prompt: {prompt[:200]}")


def candidate_ids(prompt: str) -> dict[str, str]:
    """'mcp:<id>:<tool> | Server.tool: …' lines in a pick prompt -> {"Server.tool": id}."""
    return {m.group(2): m.group(1) for m in re.finditer(r"^(mcp:\S+) \| (\S+):", prompt, re.M)}


def picker(*wanted: str, extra: str | None = None):
    """Answer a pick prompt with the ids of these Server.tool names (only if offered)."""
    def handle(prompt: str):
        ids = candidate_ids(prompt)
        chosen = [ids[w] for w in wanted if w in ids] + ([extra] if extra else [])
        if "Pick the ONE tool" in prompt:
            return {"tool_id": chosen[0] if chosen else None}
        return {"tool_ids": chosen}
    return handle


@pytest.fixture
def llm(monkeypatch):
    gw = PromptGateway()
    monkeypatch.setattr("builder.agents.runtime._gateway", lambda: gw)

    async def no_embedding(*_a, **_k):
        return None

    monkeypatch.setattr(catalog_engine, "embed_text", no_embedding)
    return gw


@pytest_asyncio.fixture
async def catalog(db, tenant):
    servers = {
        "Gmail": [("send_email", "Send an email to recipients"), ("search_emails", "Search emails in the Gmail inbox")],
        "Slack": [("post_message", "Post a message to a Slack channel"), ("list_channels", "List Slack channels")],
        "Notion": [("create_page", "Create a Notion page"), ("search", "Search Notion pages")],
    }
    out = {}
    for name, tools in servers.items():
        server = VendorMCPServer(name=name, description=f"{name} tools", is_global=True, transport="streamable_http",
                                 server_url=f"https://{name.lower()}.example/mcp", auth_config={})
        db.add(server)
        await db.flush()
        for tool, desc in tools:
            db.add(MCPTool(mcp_server_id=server.id, name=tool, description=desc,
                           input_schema={"type": "object", "properties": {"text": {"type": "string"}}}))
        out[name] = server
    await db.commit()
    return out


GRAPH = {
    "name": "Inbox digest",
    "nodes": [
        {"id": "n1", "type": "input"},
        {"id": "n2", "type": "agent", "name": "Inbox Summarizer", "role": "Email analyst", "goal": "Summarize today's emails",
         "instructions": "Be brief.", "needs": "search emails in the Gmail inbox"},
        {"id": "n3", "type": "tool", "label": "Post to Slack", "need": "post the summary message to a Slack channel"},
        {"id": "n4", "type": "output"},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}, {"id": "e2", "source": "n2", "target": "n3"}, {"id": "e3", "source": "n3", "target": "n4"}],
}


# ── Agent drafts ─────────────────────────────────────────────────────────────


async def test_agent_draft_picks_tools_from_the_hybrid_search(tenant_client, llm, catalog):
    llm.on("A user wants to build an AI agent", {
        "name": "Inbox Helper", "role": "Email assistant", "goal": "Summarize email and share it",
        "instructions": "Never invent emails.", "needs": "search emails in Gmail and post a message to Slack",
    })
    llm.on("Pick the tools this agent", picker("Gmail.search_emails", "Slack.post_message", extra="mcp:not-offered:tool"))
    r = await tenant_client.post("/api/v1/builder/assist/agent", json={"description": "summarize my gmail into slack"})
    assert r.status_code == 200, r.text
    draft = r.json()
    names = {(t["server_name"], t["tool_name"]) for t in draft["tools"]["agent"]}
    assert names == {("Gmail", "search_emails"), ("Slack", "post_message")}  # the made-up id was ignored
    assert len(draft["config"]["tool_ids"]) == 2
    assert {s["server_name"] for s in draft["needs_connection"]} == {"Gmail", "Slack"}
    # The model only ever saw the shortlist, never the whole catalog.
    pick = llm.seen("Pick the tools this agent")[0]
    assert "Notion.create_page" not in pick

    # The draft saves as-is through the normal endpoint.
    r = await tenant_client.post("/api/v1/builder/agents", json={k: draft[k] for k in ("name", "role", "goal", "instructions", "config")})
    assert r.status_code == 201, r.text


async def test_agent_with_no_needs_gets_no_tools(tenant_client, llm, catalog):
    llm.on("A user wants to build an AI agent", {"name": "Poet", "role": "Poet", "goal": "Write poems", "instructions": "", "needs": ""})
    draft = (await tenant_client.post("/api/v1/builder/assist/agent", json={"description": "writes poems"})).json()
    assert draft["config"]["tool_ids"] == [] and not llm.seen("Pick the tools")


# ── Workflow drafts ──────────────────────────────────────────────────────────


async def test_workflow_draft_end_to_end(db, tenant_client, llm, catalog):
    llm.on("A user described a business process", GRAPH)
    llm.on("Pick the tools this agent", picker("Gmail.search_emails"))
    llm.on("Pick the ONE tool", picker("Slack.post_message"))
    r = await tenant_client.post("/api/v1/builder/assist/workflow", json={"description": "Every morning summarize my Gmail and post it to Slack"})
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["problems"] == [] and draft["name"] == "Inbox digest"
    nodes = {n["id"]: n for n in draft["nodes"]}
    assert nodes["n2"]["draft_agent"]["name"] == "Inbox Summarizer"
    assert nodes["n2"]["draft_agent"]["config"]["tool_ids"] == [f"mcp:{catalog['Gmail'].id}:search_emails"]
    assert nodes["n3"]["tool_id"] == f"mcp:{catalog['Slack'].id}:post_message"
    assert [nodes[i]["position"]["x"] for i in ("n1", "n2", "n3", "n4")] == [0, 300, 600, 900]

    # Saving the draft creates the agent step's agent as one of the workflow's own.
    r = await tenant_client.post(WF, json={k: draft[k] for k in ("name", "nodes", "edges", "config")})
    assert r.status_code == 201, r.text
    saved = r.json()
    step = next(n for n in saved["nodes"] if n["id"] == "n2")
    assert "draft_agent" not in step and step["agent_id"] == saved["agents"][0]["id"]
    assert saved["agents"][0]["workflow_id"] == saved["id"]
    pre = (await tenant_client.post(f"{WF}/{saved['id']}/preflight")).json()
    assert {p["code"] for p in pre["problems"]} == {"not_connected"}


async def test_a_broken_graph_goes_back_to_the_model_once(tenant_client, llm, catalog):
    broken = {**GRAPH, "nodes": GRAPH["nodes"] + [{"id": "n5", "type": "input"}]}  # two triggers
    llm.on("A user described a business process", broken)
    llm.on("has these problems", GRAPH)
    llm.on("Pick the tools this agent", picker("Gmail.search_emails"))
    llm.on("Pick the ONE tool", picker("Slack.post_message"))
    draft = (await tenant_client.post("/api/v1/builder/assist/workflow", json={"description": "digest"})).json()
    assert draft["problems"] == []
    assert "only one trigger" in llm.seen("has these problems")[0]


async def test_a_step_no_tool_can_do_is_flagged_not_forced(tenant_client, llm, catalog):
    graph = json.loads(json.dumps(GRAPH))
    graph["nodes"][2]["need"] = "fax the report to the bank"
    llm.on("A user described a business process", graph)
    llm.on("Pick the tools this agent", picker("Gmail.search_emails"))
    llm.on("Pick the ONE tool", {"tool_id": None})
    draft = (await tenant_client.post("/api/v1/builder/assist/workflow", json={"description": "fax things"})).json()
    assert [(p["code"], p["node_id"]) for p in draft["problems"]] == [("tool_not_found", "n3")]
    assert "tool_id" not in next(n for n in draft["nodes"] if n["id"] == "n3")


# ── Editing ──────────────────────────────────────────────────────────────────


async def _saved_flow(client) -> tuple[dict, str]:
    agent = (await client.post("/api/v1/builder/agents", json={"name": "Writer", "role": "writer", "goal": "write", "config": {}})).json()
    body = {
        "name": "Flow",
        "nodes": [{"id": "in", "type": "input", "position": {"x": 0, "y": 0}},
                  {"id": "a", "type": "agent", "agent_id": agent["id"], "position": {"x": 300, "y": 0}},
                  {"id": "out", "type": "output", "position": {"x": 600, "y": 0}}],
        "edges": [{"id": "e1", "source": "in", "target": "a"}, {"id": "e2", "source": "a", "target": "out"}],
    }
    return (await client.post(WF, json=body)).json(), agent["id"]


async def test_edit_adds_a_step_in_place(tenant_client, llm, catalog):
    wf, _ = await _saved_flow(tenant_client)
    llm.on("You are editing an EXISTING AI workflow", {
        "summary": "Added a Slack post after the writer.", "answer": None,
        "ops": [{"op": "add_node", "id": "new1", "type": "tool", "need": "post the draft to a Slack channel", "after": "a"}],
    })
    llm.on("Pick the ONE tool", picker("Slack.post_message"))
    r = await tenant_client.post("/api/v1/builder/assist/workflow-edit", json={"instruction": "post it to slack after writing", **{k: wf[k] for k in ("name", "nodes", "edges", "config")}, "workflow_id": wf["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    new = next(n for n in out["nodes"] if n["type"] == "tool")
    assert new["tool_id"] == f"mcp:{catalog['Slack'].id}:post_message"
    assert {(e["source"], e["target"]) for e in out["edges"]} == {("in", "a"), ("a", new["id"]), (new["id"], "out")}
    assert out["problems"] == [] and out["changes"][0].startswith("Added")
    assert new["position"]["x"] == 600
    # Untouched steps are exactly as they were.
    assert next(n for n in out["nodes"] if n["id"] == "a") == next(n for n in wf["nodes"] if n["id"] == "a")


async def test_a_failed_edit_is_repaired_once(tenant_client, llm, catalog):
    wf, _ = await _saved_flow(tenant_client)
    llm.on("Your operations failed", {"summary": "Renamed.", "answer": None, "ops": [{"op": "rename_workflow", "name": "Better"}]})
    llm.on("You are editing an EXISTING AI workflow", {"summary": "x", "answer": None, "ops": [{"op": "remove_node", "id": "ghost"}]})
    out = (await tenant_client.post("/api/v1/builder/assist/workflow-edit", json={"instruction": "rename it", **{k: wf[k] for k in ("name", "nodes", "edges", "config")}})).json()
    assert out["name"] == "Better"
    assert "no step with id 'ghost'" in llm.seen("Your operations failed")[0]


async def test_replacing_a_shared_agent_only_changes_this_workflow(db, tenant_client, llm, catalog):
    wf, shared_id = await _saved_flow(tenant_client)
    llm.on("You are editing an EXISTING AI workflow", {"summary": "Made the writer formal.", "answer": None,
           "ops": [{"op": "replace_agent", "id": "a", "instructions": "Write formally."}]})
    out = (await tenant_client.post("/api/v1/builder/assist/workflow-edit", json={"instruction": "make the writer formal", **{k: wf[k] for k in ("name", "nodes", "edges", "config")}})).json()
    step = next(n for n in out["nodes"] if n["id"] == "a")
    assert step["draft_agent"]["name"] == "Writer" and step["draft_agent"]["instructions"] == "Write formally."

    r = await tenant_client.patch(f"{WF}/{wf['id']}", json={"nodes": out["nodes"], "edges": out["edges"]})
    assert r.status_code == 200, r.text
    saved = r.json()
    new_agent = saved["agents"][0]
    assert new_agent["instructions"] == "Write formally." and new_agent["id"] != shared_id
    shared = await db.get(BuilderAgent, shared_id)
    await db.refresh(shared)
    assert shared.instructions == "" and shared.workflow_id is None  # the shared agent is untouched


async def test_question_returns_an_answer_and_no_changes(tenant_client, llm, catalog):
    wf, _ = await _saved_flow(tenant_client)
    llm.on("You are editing an EXISTING AI workflow", {"summary": None, "answer": "It writes, then outputs.", "ops": []})
    out = (await tenant_client.post("/api/v1/builder/assist/workflow-edit", json={"instruction": "what does this do?", **{k: wf[k] for k in ("name", "nodes", "edges", "config")}})).json()
    assert out["answer"] == "It writes, then outputs." and out["changes"] == [] and out["nodes"] == wf["nodes"]


# ── Small endpoints ──────────────────────────────────────────────────────────


async def test_tool_search(tenant_client, llm, catalog, db, tenant_user):
    from vendor.services import mcp_auth

    await mcp_auth.store_server_credentials(db, server_id=catalog["Slack"].id, credentials={}, tenant_id=tenant_user.tenant_id, user_id=tenant_user.id)
    await db.commit()
    hits = (await tenant_client.get("/api/v1/builder/tools/search", params={"q": "post a message to slack"})).json()
    assert hits[0]["server_name"] == "Slack" and hits[0]["tool_name"] == "post_message"
    assert hits[0]["connected"] is True and hits[0]["risk"] == "edit"


async def test_improve_text_and_unavailable_model(tenant_client, llm, monkeypatch):
    llm.on("Rewrite their rough draft", "Summarize every unread email in three bullet points.")
    r = await tenant_client.post("/api/v1/builder/assist/improve-text", json={"field": "goal", "text": "sum emails"})
    assert r.json() == {"text": "Summarize every unread email in three bullet points."}

    class Down:
        async def complete(self, *a, **k):
            raise RuntimeError("No configured provider available")

    monkeypatch.setattr("builder.agents.runtime._gateway", lambda: Down())
    r = await tenant_client.post("/api/v1/builder/assist/agent", json={"description": "anything"})
    assert r.status_code == 503 and "isn't available" in r.json()["detail"]
