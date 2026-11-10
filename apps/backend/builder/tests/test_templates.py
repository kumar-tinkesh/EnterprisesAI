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
    assert {"JobSpy", "Startup Jobs", "LinkedIn", "Tavily", "Google Sheets", "Gmail", "WhatsApp"} == set(systems)
    # Only the tracker can't do without its system; Gmail and WhatsApp are skipped when not connected.
    assert [s for s, v in systems.items() if v["required"]] == ["Google Sheets"]

    r = await tenant_client.post("/api/v1/builder/templates/job_finder")
    assert r.status_code == 201, r.text
    wf = r.json()
    agents = [n for n in wf["nodes"] if n["type"] == "agent"]
    assert len(agents) == 8 and all(n.get("agent_id") and not n.get("draft_agent") for n in agents)
    code = {n["id"]: n for n in wf["nodes"] if n["type"] == "code"}
    assert {k: n["code"] for k, n in code.items()} == {
        "sj": "job_seen", "cf": "job_filter", "rk": "job_rank", "c1": "job_contacts", "rp": "job_report",
        "s1": "job_tracker", "s2": "job_drafts", "wa": "job_whatsapp",
        "l1": "lane_indeed", "l2": "lane_naukri", "l3": "lane_glassdoor", "l4": "lane_startups", "l5": "lane_linkedin"}
    # The steps whose calls are fixed call their tools themselves – no AI turn decides them.
    assert [n["system"] for n in code["s1"]["tool_needs"]] == ["Google Sheets"] and code["s1"]["tool_needs"][0]["required"]
    assert [n["system"] for n in code["s2"]["tool_needs"]] == ["Gmail"]
    assert [n["system"] for n in code["wa"]["tool_needs"]] == ["WhatsApp"]
    sources = lambda target: {e["source"] for e in wf["edges"] if e["target"] == target}  # noqa: E731
    lanes = {f"l{i}" for i in range(1, 8)}
    # Seven lanes side by side, all from the profile; the join also gets the tracker's URLs.
    assert all(sources(lane) == {"b1"} for lane in lanes) and sources("j1") == lanes | {"sj"}
    assert sources("cf") == {"b1", "j1"} and all(sources(f"m{i}") == {"cf"} for i in range(1, 5))
    # Contacts and letters side by side; the Report reads the WhatsApp field straight from the input.
    assert sources("rk") == {"cf", "j2"} and sources("c1") == {"rk"} and sources("w1") == {"rk", "b1"}
    assert sources("rp") == {"rk", "c1", "w1", "in"}
    # Auto: no approval step, and the saves don't wait for each other.
    assert not [n for n in wf["nodes"] if n["type"] == "human_approval"]
    assert sources("s1") == sources("s2") == sources("wa") == {"rp"}
    assert "WhatsApp" not in saved_profile_lines(wf)
    assert wf["config"]["approval_overrides"]["edit"] == "never"
    # A failed lane isn't run again: the join goes on without it.
    assert all(n.get("retry") == {"max_attempts": 1} for n in wf["nodes"] if n["id"] in lanes)
    saved = {a.name: a for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.workflow_id == wf["id"]))).scalars()}
    # The open-web lanes are AI steps with a time budget and a hard call limit.
    lane_agents = [saved[n["label"]] for n in wf["nodes"] if n["id"] in lanes and n["type"] == "agent"]
    assert len(lane_agents) == 2 and all(a.config["tools"]["time_budget_seconds"] and a.config["tools"]["max_calls"] <= 5
                                         for a in lane_agents)
    # Every lane searches from the profile's lines – nearby cities and the level the resume says.
    from builder.templates.job_finder import SEARCH
    assert all(SEARCH in a.instructions for a in lane_agents)
    assert all(f"\n{line}:" in saved["Profile Builder"].instructions for line in ("Nearby", "Region", "Seniority", "Skip titles", "Query", "Target"))


async def test_a_step_that_runs_without_its_systems(db, tenant_client, demo):
    gleif = {"system": "GLEIF", "match": ["pipeworx-io/mcp-gleif"]}

    async def problems(**config) -> list[dict]:
        r = await tenant_client.post("/api/v1/builder/agents", json={
            "name": "Alert", "role": "assistant", "goal": "Alert", "config": {"tool_needs": [gleif], **config},
        })
        r = await tenant_client.post(f"/api/v1/builder/agents/{r.json()['id']}/runs", json={"input": "go"})
        return r.json().get("problems") or [] if r.status_code == 422 else []

    assert (await problems())[0]["code"] == "need_missing"
    assert await problems(runs_without_needs=True) == []
    # A required system still stops it.
    assert (await problems(runs_without_needs=True, tool_needs=[{**gleif, "required": True}]))[0]["code"] == "need_missing"


def saved_profile_lines(wf: dict) -> str:
    from builder.templates.job_finder import PROFILE
    return PROFILE["instructions"].split("PROFILE\n", 1)[1].split("Search phrases", 1)[0]


def test_job_finder_code_steps():
    """Filter -> Rank -> Report on a small sample: duplicates merged; old / fee / senior / too-experienced / far-away /
    non-job-page / tracked jobs dropped; one batch per Matcher; the score worked out in code from skills the post
    really names; contacts and the WhatsApp number checked."""
    import json
    from datetime import date, timedelta

    from builder.templates.job_finder_steps import job_filter, job_rank, job_report
    from builder.workflows.code_steps import CodeInput

    today, old = date.today().isoformat(), (date.today() - timedelta(days=40)).isoformat()
    profile = ("PROFILE\nName: Asha\nSkills: Python, LangChain\nRoles: Generative AI Engineer\nHome: Noida, India\n"
               "Nearby: Delhi\nRegion: Delhi NCR\nLocations: Noida, Delhi, Remote\nType: full-time\n"
               "Experience: 2 years\nSeniority: junior\nSkip titles: Senior, Lead\nPosted within: 14\nTarget: 1\n"
               "Min pay: Any\nExclude: unpaid, roles asking for a fee")
    j = lambda **k: json.dumps(k)  # noqa: E731
    lanes = "\n\n".join([
        "--- Indeed ---\n" + "\n".join([
            j(company="Acme AI", role="Generative AI Engineer", location="Noida", job_type="fulltime", posted=today,
              url="https://in.indeed.com/viewjob?jk=1&utm_source=x", requirements="Python, LangChain, Docker",
              experience="1-3 Yrs"),
            j(company="Old Co", role="AI Engineer", location="Delhi", posted=old, url="https://x.com/old"),
            j(company="Big Co", role="Senior AI Engineer", location="Delhi", url="https://x.com/sr"),
            j(company="Scam", role="AI Engineer", location="Delhi", url="https://x.com/s", requirements="registration fee"),
            j(company="Deep Co", role="AI Engineer", location="Delhi",
              url="https://www.naukri.com/job-listings-ai-engineer-deep-co-delhi-5-to-9-years-123"),
            j(company="Far Co", role="AI Engineer", location="Bengaluru", url="https://far.io/1"),
            j(company="Glass Co", role="AI Engineer", location="Delhi", url="https://www.glassdoor.co.in/Overview/W-EI_IE1.htm"),
            j(company="Newbie Co", role="AI Engineer - Fresher", location="Delhi", url="https://n.io/1"),
        ]),
        "--- LinkedIn ---\n" + "\n".join([
            j(company="ACME AI", role="Generative AI Engineer", location="Noida", url="https://in.indeed.com/viewjob?jk=1",
              pay="15 LPA"),
            j(company="Remote Inc", role="Python Developer", location="Remote", work_type="remote", url="https://r.io/1",
              requirements="Python, Django"),
            j(company="Seen Co", role="AI Engineer", location="Noida", url="https://seen.com/1"),
        ]),
        "--- Seen Jobs ---\nSEEN\nhttps://seen.com/1",
    ])
    f = job_filter(CodeInput(parts=[("Profile Builder", profile), ("All jobs", lanes)], request="",
                             targets=[("m1", "agent"), ("m2", "agent"), ("m3", "agent"), ("rk", "code")]))
    jobs = json.loads(f.routed["rk"])["jobs"]
    assert [x["company"] for x in jobs] == ["Acme AI", "Remote Inc"], f.output
    assert jobs[0]["pay"] == "15 LPA" and "LinkedIn" in jobs[0]["source"]  # the duplicate's details are kept
    assert jobs[0]["job_type"] == "full-time" and jobs[0]["years"] == "1-3"
    counts = json.loads(f.routed["rk"])["counts"]
    assert counts["too_much_experience"] == 1 and counts["outside_places"] == 1 and counts["not_a_job_page"] == 1
    assert '"id": "J1"' in f.routed["m1"] and '"id": "J2"' in f.routed["m2"] and f.routed["m3"] == "NO JOBS"

    # The Matchers only list skills; "2026 batch" isn't in the post, so it doesn't count.
    scores = ("--- Matcher 1 ---\n" + j(id="J1", matched=["Python", "LangChain", "2026 batch"], missing=["Docker"])
              + "\n--- Matcher 2 ---\n" + j(id="J2", matched=["Python"], missing=["Django"], ruled_out=""))
    r = job_rank(CodeInput(parts=[("Code Filter", f.routed["rk"]), ("All scores", scores)], request="",
                           targets=[("w1", "agent"), ("rp", "code")]))
    ranked = json.loads(r.routed["rp"])
    assert [x["company"] for x in ranked["top"]] == ["Acme AI"] and [x["company"] for x in ranked["extra"]] == ["Remote Inc"]
    acme = ranked["top"][0]
    # Skills 2 of 3 (27) + experience fits (25) + at Home (15) + pay given (10) + posted today (10).
    assert acme["score"] == 87 and "2026 batch" not in acme["why"] and acme["missing"] == "Docker"

    contact = "\n".join([j(company="Acme AI", name="Riya Sharma", title="Recruiter", email="careers@acmeai.com",
                           link="https://linkedin.com/in/riya"),
                         j(company="Remote Inc", name="none found", email="ir@remote.io")])
    writer = ("## Skill gaps\nNone\n\n## Cover letters\n\n### Acme AI – Generative AI Engineer\nDear Hiring Team,\n"
              "I built LangChain apps and know Docker well.\n\nResume tips:\n- Move LangChain up\n- Add metrics")
    report = job_report(CodeInput(parts=[("Rank", r.routed["rp"]), ("Contact Finder", contact),
                                         ("Report Writer", writer), ("Input", "Inputs:\n- whatsapp: 98765 43210")],
                                  request="", targets=[])).output
    assert "## All new matches" in report and "### Near you (1)" in report and "## More new matches" in report
    assert "## Top 2" in report  # both new matches, nothing earlier in the tracker
    assert "Riya Sharma (Recruiter)" in report and "ir@remote.io" not in report
    assert "To: careers@acmeai.com" in report and "Dear Riya," in report and "Subject: Application for Generative AI Engineer – Asha" in report
    assert "⚠ The letter mentions Docker" in report
    # A letter the writer wrote for a weaker match is left out.
    weak = writer + "\n\n### Remote Inc – Python Developer\nDear Hiring Team,\nHello."
    out = job_report(CodeInput(parts=[("Rank", r.routed["rp"]), ("Report Writer", weak)], request="",
                               targets=[("s2", "code")]))
    assert [d["heading"] for d in json.loads(out.routed["s2"])["drafts"]] == ["Acme AI – Generative AI Engineer"]
    assert "WhatsApp to: 919876543210" in report
    assert report.splitlines()[2].startswith("2 new matches scored 50+")
    # No WhatsApp field and no number on the resume: no alert.
    report = job_report(CodeInput(parts=[("Rank", r.routed["rp"])], request="", targets=[])).output
    assert "WhatsApp to: none" in report


async def test_max_calls_holds_within_one_turn(db, tenant_client, demo, gateway, runtime):
    """A model asking for more calls in one turn than the step may make gets the first ones run, the rest not."""
    await _demo_from_repo(db, demo)
    r = await tenant_client.post("/api/v1/builder/agents", json={
        "name": "Helper", "role": "assistant", "goal": "Help",
        "config": {"tool_needs": [DEMO], "tools": {"max_calls": 2}},
    })
    gw = gateway([reply(calls=[("demo_labs__echo", {"text": f"hi {i}"}) for i in range(5)]), reply("done")])
    r = await tenant_client.post(f"/api/v1/builder/agents/{r.json()['id']}/runs", json={"input": "go"})
    await worker(runtime).drain()
    assert (await get_run(tenant_client, r.json()["id"]))["status"] == "succeeded"
    answers = [m.content for m in gw.requests[1].messages if m.role == "tool"]
    assert len(answers) == 5 and sum(a.startswith("Not run") for a in answers) == 3


class FakeTools:
    """A code step's tools, answering from a script: {(system, tool): answer text or fn(arguments)}."""

    def __init__(self, answers: dict):
        self.answers, self.calls = answers, []

    def has(self, system, tool=None):
        return any(s == system and (tool is None or t == tool) for s, t in self.answers)

    async def call(self, system, tool, arguments, *, key, timeout=60, ask=None, note=""):
        from builder.workflows.code_steps import ToolAnswer

        self.calls.append((tool, arguments, ask))
        answer = self.answers.get((system, tool))
        if answer is None:
            return ToolAnswer(text="not connected", is_error=True)
        text = answer(arguments) if callable(answer) else answer
        return ToolAnswer(text=text, declined=text == "DECLINED")


async def test_job_finder_savers_and_contacts():
    import json

    from builder.templates.job_finder_actions import job_contacts, job_drafts, job_seen, job_tracker, job_whatsapp
    from builder.workflows.code_steps import CodeInput

    sheet = json.dumps({"id": "S1", "name": "Internship Tracker"})
    data = json.dumps({"valueRanges": [{"values": [
        ["Date found", "Company", "Role", "Location", "Type", "Pay", "Score", "Deadline", "Apply URL", "Status", "Found via"],
        ["2026-11-01", "Old", "AI", "Noida", "full-time", "", "70", "", "https://old.io/1", "New", "x"]]}]})
    sheets = {("Google Sheets", "search_spreadsheets"): sheet + "\n\n" + json.dumps({"id": "S2", "name": "Other"}),
              ("Google Sheets", "list_sheets"): "Sheet1", ("Google Sheets", "get_sheet_data"): data,
              ("Google Sheets", "update_cells"): "ok", ("Google Sheets", "create_spreadsheet"): "{}"}
    seen = await job_seen(CodeInput(parts=[], request="", targets=[], tools=FakeTools(sheets)))
    assert seen.output.startswith("SEEN\nhttps://old.io/1\n")
    assert json.loads(seen.output.splitlines()[2])["Company"] == "Old"  # the rows too, for the top list

    job = lambda c, u, s: {"company": c, "role": "AI Engineer", "location": "Noida", "job_type": "full-time",  # noqa: E731
                           "pay": "", "score": s, "deadline": "", "url": u, "source": "LinkedIn"}
    report = json.dumps({"date": "2026-11-09", "top": [job("Acme", "https://acme.io/1", 80), job("Old", "https://old.io/1", 70)],
                         "extra": [job("Beta", "https://beta.io/2", 55)], "ask": True,
                         "drafts": [{"heading": "Acme – AI Engineer", "to": "", "subject": "Application", "body": "Dear"},
                                    {"heading": "Beta – AI Engineer", "to": "careers@beta.io", "subject": "S", "body": "B"}],
                         "whatsapp": {"to": "919876543210", "message": "🎯 3 job matches"}})
    tools = FakeTools(sheets)
    out = await job_tracker(CodeInput(parts=[("Report", report)], request="", targets=[], tools=tools))
    assert out.output == "Tracker: 2 new jobs added – https://docs.google.com/spreadsheets/d/S1"
    rows = [c for c in tools.calls if c[0] == "update_cells"]
    # The old tracker gets its two new headings, then ONE update for the new rows (the tracked one skipped).
    assert rows[0][1]["range"] == "L1:M1" and rows[1][1]["range"] == "A3:A4".replace("A4", "M4")
    assert [r[9] for r in rows[1][1]["data"]] == ["New", "Extra"] and rows[1][2] is True  # asks: the field said yes

    gmail = FakeTools({("Gmail", "get_profile"): '{"emailAddress": "me@gmail.com"}', ("Gmail", "create_draft"): "ok"})
    out = await job_drafts(CodeInput(parts=[("Report", report)], request="", targets=[], tools=gmail))
    assert out.output.startswith("Gmail: 2 drafts saved")
    assert [c[1]["to"] for c in gmail.calls if c[0] == "create_draft"] == ["me@gmail.com", "careers@beta.io"]

    wa = FakeTools({("WhatsApp", "send_message"): "DECLINED"})
    out = await job_whatsapp(CodeInput(parts=[("Report", report)], request="", targets=[], tools=wa))
    assert out.output.startswith("WhatsApp: not sent") and wa.calls[0][1]["recipient"] == "919876543210"
    no_number = report.replace('"919876543210"', '""')
    assert (await job_whatsapp(CodeInput(parts=[("Report", no_number)], request="", targets=[], tools=wa))).output \
        == "WhatsApp: no number given – skipped."

    ranked = json.dumps({"profile": {"home": "Noida, India"}, "top": [job("Acme Labs", "https://acme.io/1", 80)]})
    people = ("Riya Sharma\n\nTalent Acquisition at Acme Labs\n\nNoida\n\nView\n\nCurrent: Recruiter at Acme Labs\n\n"
              "LinkedIn Member\n\nRecruiter at Acme Labs\n\nDelhi\n\nView\n\nhttps://www.linkedin.com/in/riya-sharma-1/")
    found = FakeTools({("Tavily", "tavily_search"): "Title: Careers\nURL: https://acmelabs.com/careers\nContent: write to "
                                                       "careers@acmelabs.com or ir@acmelabs.com",
                       ("Tavily", "tavily_extract"): "URL: https://acme.io/1\nRaw Content: nothing here",
                       ("LinkedIn", "search_people"): people})
    out = await job_contacts(CodeInput(parts=[("Rank", ranked)], request="", targets=[], tools=found))
    contact = json.loads(out.output.splitlines()[0])
    assert contact["name"] == "Riya Sharma" and contact["email"] == "careers@acmelabs.com"
    assert contact["link"] == "https://www.linkedin.com/in/riya-sharma-1"


async def test_job_finder_code_lanes():
    import json

    from builder.templates.job_finder_lanes import lane_linkedin, lane_naukri, linkedin_jobs
    from builder.workflows.code_steps import CodeInput

    profile = ("PROFILE\nHome: Noida, India\nNearby: Delhi\nType: full-time\nSeniority: junior\nSkip titles: Senior, Sr\n"
               "Posted within: 14\nSearch phrases: AI Engineer ; Python Developer FastAPI")
    page = ("99+ results\n\nGenerative AI Engineer\nGenerative AI Engineer\n\nAcme\n\nNoida (On-site)\n\nPosted 2 days ago\n"
            "2 days ago\n\n · \n\nEasy Apply\n\nSr. AI Engineer (Verified job)\nSr. AI Engineer \n\nBig Co\n\nDelhi\n\n"
            "₹20L/yr\n\nActively reviewing applicants\n\nPosted 1 week ago\n1 week ago")
    jobs = linkedin_jobs(page, ["11", "22"])
    assert [(j["role"], j["company"], j["location"], j["work_type"], j["url"][-4:]) for j in jobs] == [
        ("Generative AI Engineer", "Acme", "Noida", "on-site", "/11/"), ("Sr. AI Engineer", "Big Co", "Delhi", "", "/22/")]
    assert jobs[1]["pay"] == "₹20L/yr"
    # A page whose results can't all be read gives none: a shifted list would give jobs each other's links.
    assert linkedin_jobs(page, ["11"]) == []
    # A job the person already opened says "Viewed" where the others say "Posted …".
    viewed = "AI Engineer\nAI Engineer\n\nZeta\n\nDelhi\n\nViewed\n\n · \n\nEasy Apply\n\n" + page.split("99+ results\n\n", 1)[1]
    assert [j["company"] for j in linkedin_jobs(viewed, ["9", "11", "22"])] == ["Zeta", "Acme", "Big Co"]

    # JobSpy's answer cut at the size limit still gives every job before the cut, each from its own fields.
    one = {"site": "naukri", "title": "AI Engineer", "company": "Acme", "location": "Noida, India", "date_posted": "2026-11-07",
           "job_url": "https://www.naukri.com/job-listings-ai-engineer-acme-noida-1-to-3-years-1",
           "company_url": "https://www.naukri.com/acme-jobs-careers-9", "experience_range": "1-3 Yrs", "skills": "Python, RAG"}
    cut = json.dumps({"total": 2, "jobs": [one, {**one, "title": "Other"}]})[:-60]
    tools = FakeTools({("JobSpy", "search_jobs"): cut})
    out = await lane_naukri(CodeInput(parts=[("Profile Builder", profile)], request="", targets=[], tools=tools))
    found = [json.loads(ln) for ln in out.output.splitlines() if ln.startswith("{")]
    assert len(found) == 3 and found[0]["url"] == one["job_url"] and found[0]["experience"] == "1-3 Yrs"
    assert "Python, RAG" in found[0]["requirements"] and found[0]["source"] == "JobSpy (Naukri)"
    searches = [c[1] for c in tools.calls]
    assert [s["search_term"] for s in searches] == ["AI Engineer", "Python Developer FastAPI", "AI Engineer"]
    assert searches[0]["hours_old"] == 336 and "job_type" not in searches[0] and searches[-1]["is_remote"] is True

    details = {"sections": {"job_posting": "Acme\n\nAbout the job\n\nRequirements: Python, LangChain, 2+ years of experience"}}
    li = FakeTools({("LinkedIn", "search_jobs"): page, ("LinkedIn", "get_job_details"): json.dumps(details)})

    async def call(system, tool, arguments, *, key, timeout=60, ask=None):
        from builder.workflows.code_steps import ToolAnswer
        li.calls.append((tool, arguments, ask))
        if tool == "search_jobs":
            return ToolAnswer(text=page, structured={"sections": {"search_results": page}, "job_ids": ["11", "22"]})
        return ToolAnswer(text="", structured=details)
    li.call = call
    out = await lane_linkedin(CodeInput(parts=[("Profile Builder", profile)], request="", targets=[], tools=li))
    found = [json.loads(ln) for ln in out.output.splitlines() if ln.startswith("{")]
    assert [j["company"] for j in found] == ["Acme", "Big Co"]
    assert "LangChain" in found[0]["requirements"] and found[0]["experience"].startswith("2+ years")
    # One call at a time; the senior post isn't opened in full.
    assert [c[1].get("job_id") for c in li.calls if c[0] == "get_job_details"] == ["11"]


def test_job_finder_top_list_and_resume_number():
    """The report opens with a top 10 every run – new matches, then tracker jobs still open, then lower matches –
    and offers the resume's number for WhatsApp only as a suggestion."""
    import json
    from datetime import date, timedelta

    from builder.templates.job_finder_steps import earlier_jobs, job_report
    from builder.workflows.code_steps import CodeInput

    today = date.today()
    profile = {"name": "Asha", "home": "Noida, India", "nearby": "Delhi", "locations": "Noida, Delhi, Remote",
               "experience": "2 years", "seniority": "junior", "type": "full-time", "skip titles": "Senior",
               "phone": "+91 98765-43210"}
    row = lambda company, url, score, status="New", found=today, deadline="", role="AI Engineer", where="Noida": {  # noqa: E731
        "Date found": found.isoformat(), "Company": company, "Role": role, "Location": where, "Type": "full-time",
        "Pay": "", "Score": str(score), "Deadline": deadline, "Apply URL": url, "Status": status, "Found via": "x"}
    rows = [row("Open Co", "https://open.io/1", 80), row("Applied Co", "https://a.io/1", 90, status="Applied"),
            row("Not Co", "https://n.io/1", 85, status="Not interested"),
            row("Old Co", "https://o.io/1", 88, found=today - timedelta(days=45)),
            row("Shut Co", "https://s.io/1", 70, deadline=(today - timedelta(days=1)).isoformat()),
            row("Deep Co", "https://www.naukri.com/job-listings-ai-deep-co-noida-6-to-9-years-1", 92),
            row("Far Co", "https://f.io/1", 75, where="Bengaluru"),
            row("Page Co", "https://www.glassdoor.co.in/Overview/W-EI_IE1.htm", 90),
            row("Lead Co", "https://l.io/1", 95, role="Senior AI Engineer"),
            row("open co.", "https://www.linkedin.com/jobs/view/7/", 60)]  # the same job on another site
    earlier = earlier_jobs(rows, profile, today)
    # Only the one still open and still fit for them: done, old, closed, too senior, far, non-job rows stay out.
    assert [j["company"] for j in earlier] == ["Open Co"] and earlier[0]["first_seen"] == today.isoformat()

    new = {"company": "New Co", "role": "AI Engineer", "location": "Noida", "job_type": "full-time", "pay": "",
           "posted": "", "deadline": "", "url": "https://new.io/1", "score": 77, "why": "Matched: Python",
           "missing": "", "source": "x", "work_type": ""}
    low = {**new, "company": "Low Co", "url": "https://low.io/1", "score": 41}
    ranked = json.dumps({"profile": profile, "top": [new], "extra": [], "low": [low], "earlier": earlier,
                         "counts": {}, "lanes": {}})
    out = job_report(CodeInput(parts=[("Rank", ranked)], request="", targets=[("s1", "code"), ("wa", "code")]))
    top = out.output.split("## Top 3", 1)[1].split("## All new matches", 1)[0]
    assert top.index("New Co") < top.index("Open Co") < top.index("Low Co")
    assert "🆕 New" in top and f"Found {today.isoformat()}" in top and "Lower match" in top
    payload = json.loads(out.routed["s1"])
    assert [j["company"] for j in payload["low"]] == ["Low Co"]  # it goes into the tracker as a lower match
    # The WhatsApp field is empty: the resume's number is suggested, never just used.
    assert payload["whatsapp"] == {**payload["whatsapp"], "to": "919876543210", "from_resume": True}
    assert "from your resume" in out.output and "(seen before)" in payload["whatsapp"]["message"]
    # A number in the field wins, and isn't marked as a suggestion.
    out = job_report(CodeInput(parts=[("Rank", ranked), ("Input", "Inputs:\n- whatsapp: 911234567890")], request="",
                               targets=[("wa", "code")]))
    assert json.loads(out.routed["wa"])["whatsapp"]["from_resume"] is False


async def test_whatsapp_sent_to_the_number_the_person_chose():
    import json

    from builder.templates.job_finder_actions import job_whatsapp
    from builder.workflows.code_steps import CodeInput, ToolAnswer

    report = json.dumps({"drafts": [], "whatsapp": {"to": "919876543210", "from_resume": True, "message": "🎯 Top 3"}})
    asked = {}

    class Tools:
        def has(self, system, tool=None):
            return True

        async def call(self, system, tool, arguments, *, key, timeout=60, ask=None, note=""):
            asked.update(note=note)
            # The person changed the number on the card before saying yes.
            return ToolAnswer(text="ok", arguments={**arguments, "recipient": "911112223334"})

    out = await job_whatsapp(CodeInput(parts=[("Report", report)], request="", targets=[], tools=Tools()))
    assert out.output == "WhatsApp: sent to 911112223334" and "from your resume" in asked["note"]
