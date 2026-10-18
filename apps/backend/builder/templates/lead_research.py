"""Lead research: live public evidence -> profiled, qualified leads -> one report -> Notion.

Ported from the AI Marketplace's template (frontend/lib/workflowTemplates.ts) and reworked for this builder:

* Tools come from ``tool_needs`` (repo / URL of each MCP server), not from tool ids picked at creation: the
  workflow can be made before a server exists, and every run uses whatever the runner has connected by then.
* The offer and ideal customer are typed in when the run starts (input fields), so it works without a
  knowledge base; the workflow's knowledge, when it has one, is read on top.
* Evidence, profiles and the brief reach the later steps over their own lines (a step's input is all its
  sources' outputs), instead of the Marketplace's ``keep_input`` passing them on in code.
* Qualifying is a written rule set plus a quoted fit score; the brief's rules are restated in its block.
* The saved report and the Notion link both reach the output (approval -> output, saver -> output).

    in -> ICP Brief -> {Jobs, News, Web & Social} -> join -> Company Resolver
       -> Qualifier (+ brief, + evidence) -> Contact Finder -> Report Writer (+ brief, + qualifier)
       -> approval -> Notion Saver -> output (+ approval: the report itself)
"""
from __future__ import annotations

# ── Systems (where each MCP server comes from; see builder.agents.needs) ─────

LINKEDIN = ("LinkedIn", ["stickerdaniel/linkedin-mcp-server"])
JOBSPY = ("JobSpy", ["andrijdavid/jobspy-mcp", "speedyapply/jobspy"])
JOB_SCOUT = ("Job Scout", ["pabnatanawan87/job-scout-mcp"])
STARTUP_JOBS = ("Startup Jobs", ["api.startup.jobs/mcp"])
WORLD_NEWS = ("World News API", ["ddsky/world-news-api-mcp"])
NEWSMCP = ("NewsMCP", ["mcp.newsmcp.com"])
TAVILY = ("Tavily", ["tavily-ai/tavily-mcp"])
FIRECRAWL = ("Firecrawl", ["firecrawl/firecrawl-mcp-server", "mendableai/firecrawl-mcp-server"])
GLEIF = ("GLEIF", ["pipeworx-io/mcp-gleif"])
WIKIDATA = ("Wikidata", ["cyanheads/wikidata-mcp-server"])
NOTION = ("Notion", ["makenotion/notion-mcp-server"])


def need(system: tuple[str, list[str]], tools: list[str], *, required: bool = False) -> dict:
    return {"system": system[0], "match": system[1], "tools": tools, "required": required}


# ── Shared rules ─────────────────────────────────────────────────────────────

EVIDENCE_TABLE = "Company | Domain | Country | Service | Type | Quote | Source URL | Date | Found via"

EVIDENCE_RULES = (
    "Record every company that shows a need for ANY of our services in the brief's countries and industries. Do not "
    "judge company size – a later step checks it. Answer with ONE markdown table: " + EVIDENCE_TABLE + ". "
    "Domain = the company's own website domain if you saw it; Service = which of our services it points to; Type = "
    "requirement (a stated need: a job post, a tender), expansion, signal (funding, hiring spree, new leader, system "
    "migration) or news; Quote = the EXACT words of the source (a job title, a headline, a sentence) – never your own "
    "summary; Source URL = the page it came from; Date = YYYY-MM-DD; Found via = the system and the site, e.g. "
    "\"LinkedIn jobs\", \"JobSpy (Indeed)\", \"Job Scout (Greenhouse)\", \"Startup Jobs\", \"World News API "
    "(Reuters)\", \"NewsMCP\", \"Tavily (company blog)\", \"LinkedIn post\". Skip anything older than 180 days, "
    "recruitment agencies posting for unnamed clients, and companies that SELL these services. Never invent a "
    "company, quote, date or URL – what you did not read in a tool result does not exist. If a source fails or is "
    "not connected, use the others and say which in one line under the table. If nothing fits, answer "
    "\"No evidence found.\" and nothing else."
)

# Read-only research: never stop a run to ask before a search.
RESEARCH = {"approvals": {"read": False}, "reliability": {"retries": 1, "request_timeout_seconds": 120}}


def agent_node(node_id: str, x: int, y: int, *, name: str, role: str, goal: str, instructions: str,
               needs: list[dict] | None = None, max_calls: int = 8, timeout: float = 30, **config) -> dict:
    cfg = {
        **RESEARCH,
        "tool_needs": needs or [],
        "tools": {"max_calls": max_calls, "timeout_seconds": timeout, "on_failure": "continue"},
        "response": {"citations": "off"},
        **config,
    }
    return {
        "id": node_id, "type": "agent", "label": name, "position": {"x": x, "y": y},
        "draft_agent": {"name": name, "role": role, "goal": goal, "instructions": instructions, "config": cfg},
    }


# ── Steps ────────────────────────────────────────────────────────────────────

ICP_BRIEF = dict(
    name="ICP Brief",
    role="lead research planner",
    goal="Work out the ideal customer profile and the search plan every later step uses.",
    instructions=(
        "The run's input fields and the request may say what we sell and who we look for; the workflow's knowledge "
        "base, when you can search it, says more (services, ideal customer, signals, who is never a lead) – search it "
        "first, with a few queries (\"what we sell\", \"ideal customer\", \"never a lead\"). An input field that is "
        "given wins over the knowledge base; an empty one is taken from it. If neither the inputs, the request nor the "
        "knowledge base says what we sell, answer only: \"Tell me what you sell – fill in What we sell or add it to the "
        "workflow's knowledge base.\" Start your answer with this block, exactly these lines (later steps read them):\n"
        "ICP\n"
        "Offer: <our services, comma-separated>\n"
        "Countries: <countries asked for, comma-separated – names or 2-letter codes; a region such as LATAM or Europe is "
        "fine; Any if none>\n"
        "Industries: <comma-separated, or Any>\n"
        "Employees: <min>-<max> (Any if not given)\n"
        "Exclude: <kinds of company that are never a lead, comma-separated – always include competitors who sell the "
        "same services and staffing/recruitment agencies>\n"
        "Then, in at most 8 bullets: for each service, 2-3 short search phrases – the roles a company would hire for "
        "and the words an announcement would use – in English AND in each country's own language (Spanish for "
        "Mexico, Portuguese for Brazil, German for Germany…). When Countries is Any, name the 3-5 markets to search "
        "first. Never name companies – the researchers find them."
    ),
)

JOBS = dict(
    name="Jobs Collector",
    role="job-post researcher",
    goal="Find job posts that show a company needs what we provide.",
    instructions=(
        "Search job posts in the brief's countries for roles our services support or replace, with the brief's "
        "phrases, in the local language too. Use EVERY job source you have at least once: LinkedIn search_jobs "
        "(country as location; at most 3, each takes about a minute); JobSpy search_jobs (Indeed, Glassdoor, Naukri, "
        "Bayt – not its LinkedIn site); Startup Jobs search_jobs (startups); Job Scout search_jobs (HN \"Who is "
        "hiring\", RemoteOK) and Job Scout list_company_jobs for a found company's Greenhouse, Lever or Ashby board. "
        "A job post at a company that does not sell that service is a finding: Type requirement, Quote = the job "
        "title as posted. At most 8 searches; aim for 5-12 findings, several per company is fine. " + EVIDENCE_RULES
    ),
    needs=[
        need(LINKEDIN, ["search_jobs", "get_job_details"]),
        need(JOBSPY, ["search_jobs"]),
        need(STARTUP_JOBS, ["search_jobs", "get_company_jobs"]),
        need(JOB_SCOUT, ["search_jobs", "list_company_jobs"]),
    ],
    max_calls=10, timeout=150,
)

NEWS = dict(
    name="News Collector",
    role="company news researcher",
    goal="Find recent news that shows a company needs what we provide, or is about to.",
    instructions=(
        "Search news from the last 90 days with the brief's phrases, in English and each country's language: funding "
        "rounds, expansion into new countries or cities, new offices or plants, a new CFO/CIO/CHRO, ERP or "
        "finance-system changes, big contract wins, layoffs that move work to a provider. Use BOTH sources: World "
        "News API search_news (its text is at most 100 characters – one short phrase per search; filter by source "
        "country and language; earliest publish date 90 days back) and NewsMCP news (one story per event, covered by "
        "many outlets; get_story gives its summary and source links). Quote = the headline or the sentence that says "
        "it; Found via names the API and the outlet. At most 8 searches. " + EVIDENCE_RULES
    ),
    needs=[
        need(WORLD_NEWS, ["search_news", "retrieve_news_articles"]),
        need(NEWSMCP, ["news", "get_story"]),
    ],
)

WEB = dict(
    name="Web & Social Collector",
    role="web and LinkedIn researcher",
    goal="Find announcements and posts on the open web and LinkedIn that show a company needs what we provide.",
    instructions=(
        "Search the open web and LinkedIn posts with the brief's phrases, in English and each country's language: "
        "press releases, company blogs, tenders and RFPs, and LinkedIn posts such as \"we're expanding to…\", "
        "\"we're building a team in…\", \"we're moving to a new ERP\". Use Tavily search (last 90 days; topic news "
        "when it fits), Firecrawl search and LinkedIn search_posts (at most 2, each takes about a minute). Quote = the "
        "sentence that says it. At most 8 searches. " + EVIDENCE_RULES
    ),
    needs=[
        need(TAVILY, ["tavily_search"]),
        need(FIRECRAWL, ["firecrawl_search"]),
        need(LINKEDIN, ["search_posts"]),
    ],
    timeout=120,
)

RESOLVER = dict(
    name="Company Resolver",
    role="company profile researcher",
    goal="Say who each company in the evidence is – website, size, industry, headquarters and parent – so it can be checked against the brief.",
    instructions=(
        "Your input is the collectors' evidence tables. List every company in them ONCE (merge spellings of the same "
        "company) and look it up, strongest evidence first. LinkedIn: search_companies finds its page "
        "linkedin.com/company/<slug>; get_company_profile with that slug – the part after /company/, never the "
        "company's name – gives employees, industry and headquarters (at most 6 LinkedIn calls). GLEIF: search_lei "
        "with the legal name, then get_lei_relationships with its LEI, gives the direct and ultimate parent (many "
        "mid-market companies have no LEI – that is fine). Wikidata: search_entities, then get_statements, for "
        "website, headquarters, industry, employees and parent when LinkedIn had nothing. A web search finds a "
        "missing website. Write each company's name EXACTLY as the evidence has it. Answer with ONLY one markdown "
        "table: Company | Domain | Employees | Industry | HQ country | Parent | Parent employees | Profile via. HQ "
        "country is where it is headquartered, not where a job is; Profile via = the systems you used (\"LinkedIn, "
        "GLEIF\"). Leave a cell empty when you could not find it – never guess. Do not repeat the evidence."
    ),
    needs=[
        need(LINKEDIN, ["search_companies", "get_company_profile"]),
        need(GLEIF, ["search_lei", "get_lei", "get_lei_relationships"]),
        need(WIKIDATA, ["wikidata_search_entities", "wikidata_get_statements"]),
        need(TAVILY, ["tavily_search"]),
        need(FIRECRAWL, ["firecrawl_search"]),
    ],
    max_calls=16, timeout=120,
)

QUALIFIER = dict(
    name="ICP Qualifier",
    role="lead qualifier",
    goal="Keep the companies that fit the brief and show a real need for what we provide, best first.",
    instructions=(
        "Your input has three parts: the ICP Brief (its ICP block holds the rules), the collectors' evidence and the "
        "Company Resolver's profiles. Judge every profiled company, in two passes.\n"
        "1) Rules – a company is OUT when: its HQ country is known and not in Countries (Any passes everything); its "
        "Employees – or, for a subsidiary, its parent's – is known and outside the range; it is one of the Exclude "
        "kinds; or all its evidence is older than 180 days. An unknown value never rules a company out – note it.\n"
        "2) Fit score 0-100 for the companies left: 40 for how directly the evidence states the need (a job post or "
        "tender for the very service beats general news), 25 for recency (last 30 days best), 20 for how well size and "
        "industry fit, 15 for more than one independent signal. Keep a score of 50 or more, best first, at most 10.\n"
        "Answer with:\n"
        "## Qualified – a table: Rank | Company | Domain | Country | Industry | Employees | Fit score | Why (one line, "
        "quoting the evidence) | Main source URL. Then, for each one, its evidence rows copied exactly from the input "
        "(" + EVIDENCE_TABLE + ") and its profile row.\n"
        "## Not qualified – a table: Company | Reason (the rule it broke, or its score).\n"
        "Use only what is in your input; never add a company or a fact."
    ),
)

CONTACTS = dict(
    name="Contact Finder",
    role="company contact researcher",
    goal="Find each qualified company's own public contact details and its relevant leaders.",
    instructions=(
        "Your input is the qualified companies with their evidence and profiles. For each qualified company, best "
        "first (at most 10): Firecrawl map its website and look for contact, about, team, leadership or impressum "
        "pages, then Firecrawl scrape the one or two best; take the public emails, phones and addresses printed "
        "there. When a company has no domain, a web search finds its site first. For leaders, LinkedIn "
        "get_company_employees (at most 3 companies) or the team page: the people who would buy our service (the "
        "head of the function it serves, CFO/COO/CIO/CHRO, founders at small companies). Answer with ONLY:\n"
        "## Contact points – Company | Domain | Type (email / phone / form / address) | Value | Page URL\n"
        "## People – Company | Name | Title | Why them | Source URL\n"
        "Never write an email or phone that a page did not show, never build one from a name pattern, and skip "
        "personal addresses. A company with nothing found gets one row \"none found\"."
    ),
    needs=[
        need(FIRECRAWL, ["firecrawl_map", "firecrawl_scrape", "firecrawl_search"]),
        need(LINKEDIN, ["get_company_employees", "get_company_profile"]),
        need(TAVILY, ["tavily_search", "tavily_extract"]),
    ],
    max_calls=20, timeout=90,
)

WRITER = dict(
    name="Report Writer",
    role="lead report writer",
    goal="Turn everything the run found into one complete lead report a person can review and act on.",
    instructions=(
        "Your input is the ICP Brief, the Qualifier's tables (qualified companies with their evidence and profiles, "
        "and the companies that did not qualify) and the Contact Finder's contacts and people. Use ONLY what is in "
        "it – never add a company, a fact, a contact or a URL. Write one markdown report:\n"
        "# Lead research – <the offer and markets in a few words>\n"
        "## Summary – what was searched (countries, industries, services), how many companies were found, how many "
        "qualified, and which sources produced them.\n"
        "## Ranked leads – one table: Rank | Company | Country | Industry | Employees | Fit score | Main signal | Date "
        "| Found via.\n"
        "## Lead details – for each qualified company, best first: ### <Company> (<domain>), then Profile (website, "
        "HQ, employees, industry, parent, and Profile via), Evidence (a table: Type | Quote | Source URL | Date | Found "
        "via – every row from the input), Why now (1-2 sentences from that evidence), Contact points, People, and "
        "Suggested angle (which of our services fits and the opening line of a first message, from the evidence).\n"
        "## Not qualified – each company with its reason.\n"
        "## Sources used – each source with how many findings it gave; say which returned nothing or was not "
        "connected.\n"
        "Keep every quote, URL and date exactly as given. A profile value the input leaves empty stays \"unknown\". "
        "When a section has nothing, write \"None found.\""
    ),
    max_output_tokens=8000,
)

SAVER = dict(
    name="Notion Saver",
    role="report publisher",
    goal="Save the approved lead report as one new Notion page under the \"Lead Research\" page.",
    instructions=(
        "Your input is the lead report; a person approved it. Save it with exactly these calls:\n"
        "1) API-post-search with query \"Lead Research\" and filter {\"property\": \"object\", \"value\": \"page\"} – "
        "take the id of the page titled exactly \"Lead Research\". If there is none, stop and answer: \"No Notion page "
        "named Lead Research is shared with the integration – create it, share it with the integration and run "
        "again.\" Never create a page at the workspace root.\n"
        "2) API-post-page with parent {\"page_id\": <that id>} and properties {\"title\": [{\"text\": {\"content\": "
        "\"Lead research – <today's date> – <the report's title words>\"}}]}.\n"
        "3) API-update-page-markdown with the new page's id, type \"replace_content\" and replace_content "
        "{\"new_str\": <the report exactly as you received it, from its \"# Lead research\" heading on>}. If that call "
        "fails, append the report with API-patch-block-children instead.\n"
        "Then answer with ONLY: \"Saved to Notion: <the new page's URL>\". Never say it was saved unless these calls "
        "succeeded – on an error, answer with the error."
    ),
    needs=[need(NOTION, ["API-post-search", "API-post-page", "API-update-page-markdown", "API-patch-block-children"], required=True)],
    max_calls=6, timeout=60,
)


def _llm(spec: dict) -> dict:
    out = {k: v for k, v in spec.items() if k != "max_output_tokens"}
    if "max_output_tokens" in spec:
        out["llm"] = {"max_output_tokens": spec["max_output_tokens"]}
    return out


def build() -> dict:
    """The workflow to create: a ``WorkflowCreate`` body."""
    x = lambda i: 40 + i * 300  # noqa: E731
    lanes = [("r1", JOBS), ("r2", NEWS), ("r3", WEB)]
    nodes = [
        {
            "id": "in", "type": "input", "label": "What to look for", "position": {"x": x(0), "y": 300},
            "variables": [
                # Optional: the workflow's knowledge base can say it instead (ICP Brief reads both).
                {"name": "offer", "label": "What we sell",
                 "description": "Your services, e.g. cloud migration, managed IT support – empty = from the knowledge base"},
                {"name": "countries", "label": "Countries or regions", "description": "e.g. Mexico, Colombia – or LATAM; empty = anywhere"},
                {"name": "industries", "label": "Industries", "description": "e.g. manufacturing, retail; empty = any"},
                {"name": "company_size", "label": "Company size (employees)", "description": "e.g. 200-5000"},
                {"name": "exclude", "label": "Never a lead", "description": "e.g. banks, government, our competitors"},
            ],
        },
        agent_node("b1", x(1), 300, **ICP_BRIEF),
        *[agent_node(nid, x(2), 80 + i * 220, **_llm(spec)) for i, (nid, spec) in enumerate(lanes)],
        # "count" 1: one failed or empty source never stops the run; the join still waits for all three.
        {"id": "j1", "type": "join", "label": "All evidence", "position": {"x": x(3), "y": 300},
         "join_policy": {"mode": "count", "min_required": 1}},
        agent_node("n3", x(4), 300, **_llm(RESOLVER)),
        agent_node("q1", x(5), 300, **_llm(QUALIFIER)),
        agent_node("c1", x(6), 300, **_llm(CONTACTS)),
        agent_node("w1", x(7), 300, **_llm(WRITER)),
        {"id": "ap", "type": "human_approval", "label": "Review the report", "position": {"x": x(8), "y": 300},
         "approval_message": "Review the lead report – every lead, its evidence, sources and contacts – before it is saved to Notion."},
        # Approved just above, so the save itself doesn't ask again.
        agent_node("n5", x(9), 300, **_llm(SAVER)),
        {"id": "out", "type": "output", "label": "Lead report", "position": {"x": x(10), "y": 300},
         "output_config": {"format": "markdown", "compose": "off"}},
    ]
    lines = [
        ("in", "b1"),
        *[("b1", nid) for nid, _ in lanes],
        *[(nid, "j1") for nid, _ in lanes],
        ("j1", "n3"),
        # The qualifier sees the rules, the evidence and the profiles side by side.
        ("b1", "q1"), ("j1", "q1"), ("n3", "q1"),
        ("q1", "c1"),
        ("b1", "w1"), ("q1", "w1"), ("c1", "w1"),
        ("w1", "ap"),
        ("ap", "n5"),
        # The output gets the report (through the approval) and the saver's Notion link.
        ("ap", "out"), ("n5", "out"),
    ]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(lines)]
    return {
        "name": "Lead research",
        "description": (
            "Searches job posts, news, the web and LinkedIn live for companies that need what you sell (from the run's "
        "fields or the workflow's knowledge base), profiles them "
            "(LinkedIn, GLEIF, Wikidata), keeps the ones that fit your ideal customer, finds their own contact details, "
            "writes one sourced report and – after you approve it – saves it to Notion under a page called \"Lead "
            "Research\"."
        ),
        "nodes": nodes,
        "edges": edges,
        "config": {
            "max_run_seconds": 3600,
            "on_node_failure": "retry",
            "node_retry_count": 1,
            "node_retry_fallback": "abort",
            # Only the Notion save changes anything, and the approval step covers it.
            "approvals": {"read": False, "edit": False, "delete": True},
        },
    }


TEMPLATE = {
    "key": "lead_research",
    "name": "Lead research",
    "summary": "Live job posts, news and web signals -> qualified, sourced leads with contacts -> Notion.",
    "build": build,
}
