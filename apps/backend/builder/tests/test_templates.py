"""Tool needs (systems picked up by where their MCP server comes from) and the
workflow templates built on them — against the real demo MCP server."""
from __future__ import annotations

from sqlalchemy import select

from builder.agents.config import ToolNeed
from builder.agents.needs import pick_tools
from builder.models import BuilderAgent
from builder.tests.test_runs import demo, gateway, get_run, reply, runtime, worker  # noqa: F401  (fixtures)
from vendor.models import VendorMCPServer
from vendor.services import mcp_auth

DEMO_REPO = "https://github.com/acme/demo-mcp.git"
DEMO = {"system": "Demo Labs", "match": ["acme/demo-mcp"], "tools": ["echo"]}


async def _demo_from_repo(db, demo):
    demo.source_repo_url = DEMO_REPO
    await db.commit()
    return demo


async def _status(client, *needs) -> list[dict]:
    r = await client.post("/api/v1/builder/tool-needs/status", json={"needs": list(needs)})
    assert r.status_code == 200, r.text
    return r.json()


def test_pick_tools_finds_prefixed_names_and_falls_back_to_all():
    need = ToolNeed(system="Jobs", match=["x/jobs"], tools=["search_jobs", "list_company_jobs"])
    assert pick_tools(need, ["jobspy_search_jobs", "list_company_jobs", "other"]) == ["jobspy_search_jobs", "list_company_jobs"]
    assert pick_tools(need, ["renamed_tool", "another"]) == ["renamed_tool", "another"]


async def test_a_need_is_matched_by_repo_whatever_the_server_is_called(db, tenant_client, demo, tenant_user):
    await _demo_from_repo(db, demo)
    db.add(VendorMCPServer(name="linkdin", description="", is_global=True, transport="stdio",
                           source_repo_url="https://github.com/stickerdaniel/linkedin-mcp-server", status="UNCONNECTED"))
    await db.commit()

    ready, renamed, unverified, missing = await _status(
        tenant_client,
        DEMO,
        {**DEMO, "tools": ["no_such_tool"]},
        {"system": "LinkedIn", "match": ["stickerdaniel/linkedin-mcp-server"]},
        {"system": "GLEIF", "match": ["pipeworx-io/mcp-gleif"]},
    )
    assert ready["status"] == "ready" and ready["server_id"] == demo.id and ready["tools"] == ["echo"]
    assert renamed["status"] == "ready" and "echo" in renamed["tools"] and len(renamed["tools"]) > 1
    assert unverified["status"] == "not_verified" and unverified["server_name"] == "linkdin"
    assert missing["status"] == "missing" and missing["server_id"] is None

    await mcp_auth.delete_user_credential(db, server_id=demo.id, user_id=tenant_user.id)
    await db.commit()
    (not_connected,) = await _status(tenant_client, DEMO)
    assert not_connected["status"] == "not_connected" and not_connected["tools"] == []


async def test_needed_tools_are_offered_under_the_system_name_and_run(db, tenant_client, demo, gateway, runtime):
    await _demo_from_repo(db, demo)
    r = await tenant_client.post("/api/v1/builder/agents", json={
        "name": "Helper", "role": "assistant", "goal": "Help", "config": {"tool_needs": [DEMO]},
    })
    assert r.status_code == 201, r.text
    gw = gateway([reply(calls=[("demo_labs__echo", {"text": "hi"})]), reply("done")])

    r = await tenant_client.post(f"/api/v1/builder/agents/{r.json()['id']}/runs", json={"input": "say hi"})
    assert r.status_code == 202, r.text
    await worker(runtime).drain()

    run = await get_run(tenant_client, r.json()["id"])
    assert run["status"] == "succeeded", run
    tools = {t.name: t for t in gw.requests[0].tools}
    assert list(tools) == ["demo_labs__echo"] and tools["demo_labs__echo"].description.startswith("[Demo Labs]")
    assert "hi" in (gw.requests[1].messages[-1].content or "")


async def test_a_run_waits_for_its_systems(db, tenant_client, demo, tenant_user, runtime):
    await _demo_from_repo(db, demo)

    async def agent(*needs) -> str:
        r = await tenant_client.post("/api/v1/builder/agents", json={
            "name": "Helper", "role": "assistant", "goal": "Help", "config": {"tool_needs": list(needs)},
        })
        assert r.status_code == 201, r.text  # saving never waits for a connection
        return r.json()["id"]

    async def start(agent_id: str):
        return await tenant_client.post(f"/api/v1/builder/agents/{agent_id}/runs", json={"input": "go"})

    gleif = {"system": "GLEIF", "match": ["pipeworx-io/mcp-gleif"]}
    # Optional needs: one connected is enough.
    assert (await start(await agent(DEMO, gleif))).status_code == 202
    # Required and missing: blocked, saying what to ask the admin for.
    r = await start(await agent(DEMO, {**gleif, "required": True}))
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "need_missing"
    assert "pipeworx-io/mcp-gleif" in r.json()["problems"][0]["message"]
    # Not connected by this person: blocked, with the server to connect.
    await mcp_auth.delete_user_credential(db, server_id=demo.id, user_id=tenant_user.id)
    await db.commit()
    r = await start(await agent(DEMO))
    assert r.status_code == 422
    assert r.json()["problems"][0]["code"] == "not_connected" and r.json()["problems"][0]["server_id"] == demo.id


async def test_lead_research_template(db, tenant_client, tenant_user, runtime):
    r = await tenant_client.get("/api/v1/builder/templates")
    assert r.status_code == 200, r.text
    (lead,) = [t for t in r.json() if t["key"] == "lead_research"]
    systems = {s["system"]: s for s in lead["systems"]}
    assert {"LinkedIn", "JobSpy", "Job Scout", "Startup Jobs", "World News API", "NewsMCP", "Tavily", "Firecrawl",
            "GLEIF", "Wikidata", "Notion"} == set(systems)
    assert systems["Notion"]["required"] and all(s["status"] == "missing" for s in systems.values())

    r = await tenant_client.post("/api/v1/builder/templates/lead_research")
    assert r.status_code == 201, r.text
    wf = r.json()
    agents = [n for n in wf["nodes"] if n["type"] == "agent"]
    assert len(agents) == 9 and all(n.get("agent_id") and not n.get("draft_agent") for n in agents)
    saved = {a.name: a for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.workflow_id == wf["id"]))).scalars()}
    assert [n["system"] for n in saved["Notion Saver"].config["tool_needs"]] == ["Notion"]
    assert saved["ICP Brief"].config["tool_needs"] == []
    # The qualifier reads the brief, the evidence and the profiles together.
    assert {e["source"] for e in wf["edges"] if e["target"] == "q1"} == {"b1", "j1", "n3"}

    r = await tenant_client.post(f"/api/v1/builder/workflows/{wf['id']}/preflight")
    problems = r.json()["problems"]
    assert not r.json()["ok"] and {p["code"] for p in problems} == {"need_missing"}
    assert {p["node_id"] for p in problems} == {n["id"] for n in agents if n["id"] != "b1" and n["id"] not in ("q1", "w1")}

    assert (await tenant_client.post("/api/v1/builder/templates/nope")).status_code == 404


async def test_job_finder_template(db, tenant_client, tenant_user, runtime):
    r = await tenant_client.get("/api/v1/builder/templates")
    (finder,) = [t for t in r.json() if t["key"] == "job_finder"]
    systems = {s["system"]: s for s in finder["systems"]}
    assert {"JobSpy", "Startup Jobs", "Job Scout", "LinkedIn", "Tavily", "Firecrawl", "Google Sheets", "Gmail",
            "WhatsApp"} == set(systems)
    # Only the tracker can't do without its system; Gmail and WhatsApp are skipped when not connected.
    assert [s for s, v in systems.items() if v["required"]] == ["Google Sheets"]

    r = await tenant_client.post("/api/v1/builder/templates/job_finder")
    assert r.status_code == 201, r.text
    wf = r.json()
    agents = [n for n in wf["nodes"] if n["type"] == "agent"]
    assert len(agents) == 10 and all(n.get("agent_id") and not n.get("draft_agent") for n in agents)
    sources = lambda target: {e["source"] for e in wf["edges"] if e["target"] == target}  # noqa: E731
    # Nothing is saved or sent before the approval.
    assert sources("s1") == sources("s2") == {"ap"} and sources("wa") == {"b1", "ap", "s1", "s2"}
    assert sources("m1") == {"b1", "k1"}
    saved = {a.name: a for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.workflow_id == wf["id"]))).scalars()}
    assert [n["system"] for n in saved["Tracker Saver"].config["tool_needs"]] == ["Google Sheets"]
