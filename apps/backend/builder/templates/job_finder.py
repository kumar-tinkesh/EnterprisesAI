"""Internship & job finder: a query and/or a resume -> live openings from 7 lanes at once -> filtered and scored
in parallel -> report, tracker sheet, cover-letter drafts and a WhatsApp summary – no approval step (unless "Ask
before saving" says yes).

AI only where judgement is needed – the profile, reading web pages, which of a post's skills the candidate has, the
letters. Everything else is code (``builder.workflows.code_steps``), and the code steps with ``tool_needs`` call their
tools themselves: fixed calls, no AI turn deciding them, every one through the run's ledger.

* The request comes as a Query field ("Gen AI jobs in Noida, 10 LPA+") and/or the resume – attached with the run
  (only the steps right after the input get the file) or in the workflow's knowledge base, so a daily schedule
  works. The query wins over the fields, the fields over the resume.
* The Profile Builder writes the PROFILE block every later step reads: roles, skills, Home and the cities a commute
  away, level, the title words above it and 6-8 search phrases. Beside it, Seen Jobs reads the tracker's Apply URLs.
* Seven lanes side by side. Five are API calls made in code (``job_finder_lanes``): JobSpy per site (Indeed, Naukri,
  Glassdoor + Google Jobs), Startup Jobs and LinkedIn (one call at a time – it answers a burst with HTTP 429) – each
  job straight from the tool's fields: the post's own link, its years and skills, its description. Two open-web
  lanes (Internshala / Unstop, Wellfound / Cutshort / Instahyre) stay AI steps with a few searches and a hard call
  limit. Every lane is time-boxed; one that fails is left out and the join goes on.
* Code Filter merges duplicates (the same role at one company in several cities is one job) and drops old, closed,
  fee-asking, wrong-level, too-senior (years asked), outside-your-cities, not-a-job-page and already-tracked jobs,
  keeps the 100 most relevant and hands each Matcher its own batch (``routed``); four Matchers list each post's
  matched and missing skills; Rank works the score out in code (only skills the post really names count) and keeps
  every job scoring 50+, near you first, the top ``Target`` (25) as matches.
* Contact Finder (code, time-boxed: hiring emails on the posts and careers pages, recruiters LinkedIn names in full)
  and Report Writer (skill gaps, letters) run side by side; Report puts it together in code: an email only when it is
  the company's own hiring address, the letters' To / Subject / greeting from those facts, and the WhatsApp number
  from the WhatsApp field alone (never the resume).
* The report opens with a top 10, every run: the new matches, then jobs from earlier runs still open (the person's
  Status in the sheet – Applied, Not interested – keeps one out), then lower matches (35-49) they could still try.
* Then, in code: the tracker (every 50+ job in one update, the extra ones as "Extra", the lower ones shown as "Lower
  match"), Gmail drafts (saved, never sent) and the WhatsApp summary – to the WhatsApp field's number, or the
  resume's as a suggestion the person can change; like any message to someone, it always asks first.
* While it runs, the steps' "▸ " lines (what each found, resume tips) show live on the share page.

    in -> {Profile Builder, Seen Jobs}
    Profile Builder -> {7 lanes} -> join (+ Seen Jobs) -> Code Filter (+ profile) -> {Matcher ×4} -> join -> Rank
       (+ Code Filter) -> {Contact Finder, Report Writer (+ profile)} -> Report (+ Rank, + the input's fields)
       -> {Tracker Saver, Draft Saver, WhatsApp Notifier} -> output (+ Report)
"""
from __future__ import annotations

import builder.templates.job_finder_actions  # noqa: F401  (registers the code steps that call tools)
import builder.templates.job_finder_lanes  # noqa: F401  (registers the search lanes that run in code)
import builder.templates.job_finder_steps  # noqa: F401  (registers the code steps)
from builder.templates.job_finder_steps import TRACKER
from builder.templates.lead_research import (
    JOBSPY, LINKEDIN, STARTUP_JOBS, TAVILY, _llm, agent_node, need,
)

SHEETS = ("Google Sheets", ["xing5/mcp-google-sheets"])
GMAIL = ("Gmail", ["jimsimoy/gmail-mcp"])
WHATSAPP = ("WhatsApp", ["lharries/whatsapp-mcp"])

# A "▸ " line in a step's answer is shown live to the person running it (builder.publishing.outline: Notes).
NOTE = "▸ "
# Searches made together in one turn run side by side (builder.agents.runtime).
TOGETHER = "Make all your searches in ONE turn – call the tools together, they run side by side – then answer. "
MATCHERS = 4


# ── Shared rules ─────────────────────────────────────────────────────────────

# Every lane builds its searches from the same profile lines, nearest places first.
SEARCH = (
    "Build EVERY search from the PROFILE block: keywords = its Search phrases (the role titles, some with the "
    "strongest skill), place = Home first, then Nearby, then Remote (other Locations after those), level = its "
    "Seniority, type = its Type, recency = its Posted within. Never search a city or country the profile does not "
    "list. "
)

JOB_RULES = (
    "Answer with one JSON object per line – no table, nothing before them – with exactly these keys: company, role, "
    "location, work_type (on-site, remote or hybrid), job_type (internship or full-time), pay (the stipend or salary "
    "EXACTLY as posted, e.g. \"₹15,000/month\"; empty if not given), posted and deadline (YYYY-MM-DD; empty if not "
    "given), url (the post's OWN page – JobSpy's job_url, never its company_url; never a company, search or list "
    "page), experience (the years asked EXACTLY as posted, e.g. \"4-9 Yrs\", \"2+ years\"; empty if not given), "
    "requirements (the post's OWN words for skills and eligibility – the skills it lists, degree, batch / graduation "
    "year – at most 60 words, never your summary), source (the system and "
    "the site, e.g. \"JobSpy (Naukri)\", \"LinkedIn\", \"Tavily (Internshala)\"). List EVERY job the tools "
    "returned – later steps drop duplicates, old posts, wrong levels and score the fit – leaving out only a job in "
    "another country that is not remote-open to the Home country (never a US-only or visa-needed role for a "
    "candidate in India) and a title clearly not one of the Roles (e.g. sales for a developer). Never a top few. "
    "Never invent a company, role, pay, date or URL – what you did not read in a tool "
    "result does not exist. If a source fails, add one line after the objects saying which. Last line: \"" + NOTE +
    "<n> jobs on <the sites you searched>\" (n = your objects; 0 when none)."
)



def _lane(name: str, goal: str, instructions: str, needs: list[dict], *, time_budget: float, **tools) -> dict:
    # A JSON line per job: 100+ jobs need the room, or the answer is cut off mid-list.
    return dict(name=name, role="job search researcher", goal=goal, instructions=instructions + JOB_RULES,
                needs=needs, time_budget=time_budget, max_output_tokens=16000, **tools)


# ── Steps ────────────────────────────────────────────────────────────────────

PROFILE = dict(
    name="Profile Builder",
    role="career profile planner",
    goal="Work out who the candidate is and what to search for, from the query, the fields and the resume.",
    instructions=(
        "The resume is the file attached to the request (<attached_file>), or – when nothing is attached – it is in "
        "the workflow's knowledge base: search it (\"resume\", \"education\", \"skills\", \"projects\"). The Query "
        "field says what they want in their own words (roles, places, pay, type) and wins over everything; a filled-in "
        "field wins over the resume; an empty one is taken from the resume. If there is no resume and neither Query, "
        "Roles nor Skills is given, answer only: \"Attach your resume (PDF) or add it to the workflow's knowledge "
        "base – or at least write what you're looking for.\" Start your answer with this block, exactly these lines "
        "(later steps read them):\n"
        "PROFILE\n"
        "Name: <from the resume, or empty>\n"
        "Email: <from the resume, or empty>\n"
        "Phone: <the mobile number printed on the resume, digits only with the country code (91 for India), or "
        "none – only offered as a suggestion, never sent to without asking>\n"
        "Query: <the Query field as given, or none>\n"
        "Education: <degree, branch, college, graduation year>\n"
        "Skills: <comma-separated, strongest first, only what the resume, the query or the fields say>\n"
        "Projects: <at most 3, a few words each>\n"
        "Roles: <comma-separated>\n"
        "Home: <city, country – where the query or resume says they live or work now (current job, address); empty "
        "if neither says>\n"
        "Nearby: <comma-separated cities a daily commute from Home, biggest job markets first (Noida -> Delhi, "
        "Gurgaon, Greater Noida, Ghaziabad, Faridabad; Pune -> Pimpri-Chinchwad, Mumbai only if under 3 hours); empty "
        "if Home is empty>\n"
        "Region: <the metro area job sites use for Home and Nearby together, e.g. \"Delhi NCR\", \"Mumbai Metropolitan "
        "Region\", \"Bengaluru\"; empty if Home is empty>\n"
        "Locations: <the places the query or the Locations field names; otherwise Home, Nearby and Remote (e.g. "
        "\"Noida, Delhi, Gurgaon, Remote\"); Any only when they say Any or nothing names a place – never add Any "
        "yourself>\n"
        "Type: <from the query or the field; otherwise internship for a student or fresher, full-time for someone "
        "with work experience>\n"
        "Experience: <the field when filled in; otherwise the resume's years of full-time work, e.g. \"2.5 years\" "
        "(internships alone = fresher)>\n"
        "Seniority: <fresher (no full-time work), junior (under 5 years) or mid (5 years or more)>\n"
        "Skip titles: <title words above the Seniority – fresher and junior: Senior, Sr, Lead, Principal, Staff, "
        "Architect, Manager, Head, Director; mid: Principal, Director, Head, VP>\n"
        "Min pay: <from the query or the field, or Any>\n"
        "Posted within: <the Posted within field in days, or 14>\n"
        "Target: <the Jobs per day field, or 25>\n"
        "Exclude: <comma-separated – always include unpaid and roles asking for a fee>\n"
        "Search phrases: <6-8 phrases separated by \" ; \", best first, each at most 4 words as job boards title "
        "them, from the query, the Roles and the Experience (\"Generative AI Engineer\", \"LLM Engineer\", "
        "\"Python Developer\"; internships \"SDE Intern\"; freshers also \"Graduate Engineer Trainee\"); 2 of them "
        "add the strongest skill (\"Python Developer FastAPI\"); never a word from Skip titles, never \"full-time\" "
        "or a company>\n"
        "End with exactly 4 lines the person sees while the search runs: \"" + NOTE + "Looking for <first 2 Roles> "
        "in <Home and Nearby, then Remote>, posted in the last <Posted within> days (<Experience>)\", then 3 lines \""
        + NOTE + "Tip: <one short, concrete tip for THIS resume – what to add, move up or reword to fit the Roles>\"."
    ),
)

# The lanes that are plain API calls run in code (builder.templates.job_finder_lanes): (label, code, needs).
CODE_LANES = [
    ("Job Boards: Indeed", "lane_indeed", [need(JOBSPY, ["search_jobs"])]),
    ("Job Boards: Naukri", "lane_naukri", [need(JOBSPY, ["search_jobs"])]),
    ("Job Boards: Glassdoor + Google", "lane_glassdoor", [need(JOBSPY, ["search_jobs"])]),
    ("Startup Jobs", "lane_startups", [need(STARTUP_JOBS, ["search_jobs"])]),
    ("LinkedIn", "lane_linkedin", [need(LINKEDIN, ["search_jobs", "get_job_details"])]),
]

# The open-web lanes need reading pages, so they stay AI steps – with few searches, no raw page dumps (they filled
# the context with 200k tokens) and a hard call limit.
WEB = ("Tavily search, one site per search, max_results 10, time_range \"month\", NEVER include_raw_content (it "
       "floods the answer). A result that is a single job post (its URL names one job) is a job; a page listing "
       "many jobs is not – open at most 3 promising ones with ONE Tavily extract call (all URLs together) and take "
       "the jobs from them. ")
LANES = [
    _lane(
        "Web: Internshala + Unstop", "Find openings on Internshala and Unstop, which have no job-board connector.",
        SEARCH + TOGETHER + WEB + "Exactly these 4 searches: \"<Search phrase 1> <Home> site:internshala.com\", "
        "\"<phrase 2> <Region> site:internshala.com\", \"<phrase 1> <Home> site:unstop.com\", \"<phrase 2> work from "
        "home site:unstop.com\". ",
        [need(TAVILY, ["tavily_search", "tavily_extract"])], max_calls=5, timeout=30, time_budget=45,
    ),
    _lane(
        "Web: Wellfound + Cutshort", "Find openings on Wellfound, Cutshort, Instahyre and company career pages.",
        SEARCH + TOGETHER + WEB + "Exactly these 4 searches: \"<Search phrase 1> <Region> site:wellfound.com\", "
        "\"<phrase 1> <Home> site:cutshort.io\", \"<phrase 2> <Region> site:instahyre.com\", \"<phrase 2> <biggest "
        "Nearby city> careers\". ",
        [need(TAVILY, ["tavily_search", "tavily_extract"])], max_calls=5, timeout=30, time_budget=45,
    ),
]

MATCHER = dict(
    role="job fit checker",
    goal="Say which of each post's skills the candidate has, and whether the post rules them out.",
    instructions=(
        "Your input is the PROFILE block and a batch of jobs, one JSON object per line – or \"NO JOBS\": then answer "
        "only NONE. For EVERY job, read ITS requirements and answer one JSON object per job, one per line, in the "
        "batch's order, nothing else: {\"id\": \"<the job's id>\", \"matched\": [<skills the POST names that the "
        "profile's Skills or Projects show – copied EXACTLY as the post writes them, e.g. \"FastAPI\", \"RAG\">], "
        "\"missing\": [<skills the POST asks for that the profile lacks, as the post writes them>], \"ruled_out\": "
        "\"<empty, or the post's own words that rule the candidate out: a batch / graduation year they don't fit, a "
        "degree they don't have, a country they can't work in>\"}. A word that is not in the post's text never goes "
        "in matched – not the candidate's experience, city or batch; the score is worked out from your lists in code. "
        "Experience years and places are checked in code too – don't rule a job out for them. Never invent a "
        "requirement."
    ),
    max_output_tokens=4000,
)

WRITER = dict(
    name="Report Writer",
    role="career report writer",
    goal="Write the skill gaps and a cover letter for each top match.",
    instructions=(
        "Your input is the PROFILE block and the top matches (best first), each with the skills it is missing. The "
        "matches table, the To and Subject lines and the recruiter's name are added by another step – don't write "
        "them. Write in Markdown, exactly these two parts:\n"
        "## Skill gaps\n"
        "At most 5 bullets: a skill asked by several matches that the profile lacks – named exactly as the posts "
        "name it, one skill or one kind of tool per bullet (don't mix a framework with a database) – how many asked "
        "for it, and one concrete way to learn or show it (a small project idea). \"None\" if there are none.\n"
        "## Cover letters\n"
        "For each match scoring 70 or more, best first, at most 5: a heading \"### <Company> – <Role>\" (copied from "
        "the table), then a cover letter of at most 150 words starting \"Dear Hiring Team,\" that names the role, "
        "links ONE real project or skill from the profile to ONE quoted requirement of the post, and asks for a "
        "conversation. Then \"Resume tips:\" with 2 bullets – what to move up or reword for this post. Never claim a "
        "skill, grade or experience the profile does not have – above all none of that match's Missing skills. If "
        "no match scores 70, write \"No match scored 70 or more – no cover letters.\""
    ),
    max_output_tokens=6000,
)

def _agent(node_id: str, x: int, y: int, spec: dict, **node) -> dict:
    spec = dict(spec)
    budget = spec.pop("time_budget", None)
    out = agent_node(node_id, x, y, **_llm(spec))
    if budget:
        out["draft_agent"]["config"]["tools"]["time_budget_seconds"] = budget
    return {**out, **node}


def _code(node_id: str, x: int, y: int, code: str, label: str, needs: list[dict] | None = None) -> dict:
    """A code step; with ``needs`` it calls those systems' tools itself (builder.workflows.code_steps)."""
    return {"id": node_id, "type": "code", "code": code, "label": label, "position": {"x": x, "y": y},
            **({"tool_needs": needs} if needs else {})}


def build() -> dict:
    """The workflow to create: a ``WorkflowCreate`` body."""
    x = lambda i: 40 + i * 300  # noqa: E731
    lanes = [f"l{i}" for i in range(1, len(CODE_LANES) + len(LANES) + 1)]
    matchers = [f"m{i}" for i in range(1, MATCHERS + 1)]
    # A lane that fails isn't tried again – the join goes on with the others.
    once = {"retry": {"max_attempts": 1}}
    nodes = [
        {
            # Attach the resume with the run (📎); the query and the fields narrow or override what it says.
            "id": "in", "type": "input", "label": "Your resume + what you're looking for", "position": {"x": x(0), "y": 400},
            "variables": [
                # All optional: the resume (attached, or in the knowledge base) fills in what's empty.
                {"name": "query", "label": "What you're looking for", "description": "e.g. Gen AI / LLM jobs in Noida or remote, 10 LPA+ – wins over the resume; empty = from your resume"},
                {"name": "roles", "label": "Roles you want", "description": "e.g. SDE Intern, Data Analyst – empty = from your resume"},
                {"name": "locations", "label": "Locations", "description": "e.g. Bangalore, Pune, Remote – empty = your resume's city, the cities near it and Remote"},
                {"name": "job_type", "label": "Internship or full-time", "description": "internship, full-time or both – empty = from your resume (internship for a fresher)"},
                {"name": "experience", "label": "Experience", "description": "e.g. fresher, 1 year – empty = from your resume"},
                {"name": "min_pay", "label": "Minimum stipend / salary", "description": "e.g. ₹10,000/month – empty = any"},
                {"name": "posted_within", "label": "Posted within (days)", "type": "number", "description": "e.g. 7 – empty = 14"},
                {"name": "target", "label": "Jobs per day", "type": "number", "description": "the best this many go in the report, every other 50+ match to the tracker – empty = 25"},
                {"name": "skills", "label": "Skills", "description": "e.g. Python, React, SQL – empty = from your resume"},
                {"name": "exclude", "label": "Never show", "description": "e.g. sales roles, these companies"},
                {"name": "whatsapp", "label": "WhatsApp number for alerts", "description": "with country code, e.g. 919876543210 – empty = no message (never taken from your resume)"},
                {"name": "ask_before_saving", "label": "Ask before saving", "description": "yes = show the tracker rows and each Gmail draft for your OK first – empty = save them without asking"},
            ],
        },
        agent_node("b1", x(1), 300, **PROFILE),
        _code("sj", x(1), 560, "job_seen", "Seen Jobs", [need(SHEETS, ["search_spreadsheets", "list_sheets", "get_sheet_data"])]),
        *[{**_code(nid, x(2), 20 + i * 110, code, label, needs), **once}
          for i, (nid, (label, code, needs)) in enumerate(zip(lanes, CODE_LANES))],
        *[_agent(nid, x(2), 20 + (i + len(CODE_LANES)) * 110, spec, **once)
          for i, (nid, spec) in enumerate(zip(lanes[len(CODE_LANES):], LANES))],
        # "count" 1: a failed or empty source never stops the run.
        {"id": "j1", "type": "join", "label": "All jobs", "position": {"x": x(3), "y": 400},
         "join_policy": {"mode": "count", "min_required": 1}},
        {"id": "cf", "type": "code", "code": "job_filter", "label": "Code Filter", "position": {"x": x(4), "y": 400}},
        *[_agent(nid, x(5), 220 + i * 120, {**MATCHER, "name": f"Matcher {i + 1}"}, **once) for i, nid in enumerate(matchers)],
        {"id": "j2", "type": "join", "label": "All scores", "position": {"x": x(6), "y": 400},
         "join_policy": {"mode": "count", "min_required": 1}},
        {"id": "rk", "type": "code", "code": "job_rank", "label": "Rank", "position": {"x": x(7), "y": 400}},
        # Contacts and letters side by side: the Report puts the contact into each letter.
        _code("c1", x(8), 280, "job_contacts", "Contact Finder",
              [need(TAVILY, ["tavily_search", "tavily_extract"]), need(LINKEDIN, ["search_people"])]),
        _agent("w1", x(8), 520, WRITER),
        _code("rp", x(9), 400, "job_report", "Report"),
        # No approval step before these (auto, unless "Ask before saving" says yes): drafts are never sent, the
        # sheet is the person's own, and WhatsApp – a message to someone – always asks first by itself.
        _code("s1", x(10), 220, "job_tracker", "Tracker Saver",
              [need(SHEETS, ["search_spreadsheets", "create_spreadsheet", "list_sheets", "get_sheet_data", "update_cells"],
                    required=True)]),
        _code("s2", x(10), 400, "job_drafts", "Draft Saver", [need(GMAIL, ["get_profile", "create_draft"])]),
        _code("wa", x(10), 580, "job_whatsapp", "WhatsApp Notifier", [need(WHATSAPP, ["send_message"])]),
        {"id": "out", "type": "output", "label": "Job matches", "position": {"x": x(11), "y": 400},
         "output_config": {"format": "markdown", "compose": "off"}},
    ]
    lines = [
        ("in", "b1"), ("in", "sj"),
        *[("b1", nid) for nid in lanes],
        *[(nid, "j1") for nid in lanes], ("sj", "j1"),
        ("b1", "cf"), ("j1", "cf"),
        # Code Filter hands each Matcher its own batch and Rank the whole list.
        *[("cf", nid) for nid in matchers], ("cf", "rk"),
        *[(nid, "j2") for nid in matchers], ("j2", "rk"),
        ("rk", "c1"), ("rk", "w1"), ("b1", "w1"),
        # The Report reads the WhatsApp field from the input – never a phone number from the resume.
        ("rk", "rp"), ("c1", "rp"), ("w1", "rp"), ("in", "rp"),
        ("rp", "s1"), ("rp", "s2"), ("rp", "wa"),
        # The output gets the report and what each save did.
        ("rp", "out"), ("s1", "out"), ("s2", "out"), ("wa", "out"),
    ]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(lines)]
    return {
        "name": "Internship & job finder",
        "description": (
            "Write what you're looking for and/or attach your resume (📎) and run it – every field is optional and "
            "is read from the resume when empty (or add the resume to the workflow's knowledge base for a daily "
            "schedule). Searches Indeed, Naukri, Glassdoor, Google Jobs, Startup Jobs, LinkedIn, Internshala, Unstop, "
            "Wellfound, Cutshort and Instahyre at once – in your city first, then the "
            "cities near it and remote; drops duplicates, old posts, scams and jobs already in your tracker; scores "
            "every job against your profile with the post's own words; finds recruiters for the best ones and writes "
            f"cover letters to them; then adds every match to a Google Sheet called \"{TRACKER}\", saves the letters "
            "as Gmail drafts and sends you a WhatsApp summary. Schedule it daily for fresh matches every morning."
        ),
        "nodes": nodes,
        "edges": edges,
        "config": {
            "max_run_seconds": 1800,
            "on_node_failure": "retry",
            "node_retry_count": 1,
            "node_retry_fallback": "abort",
            "approvals": {"read": False, "edit": False, "delete": True},
            # Auto: the agents' own "ask before an edit" doesn't stop the tracker or the drafts either.
            "approval_overrides": {"edit": "never"},
        },
    }


TEMPLATE = {
    "key": "job_finder",
    "name": "Internship & job finder",
    "summary": "Query or resume -> 11 job sites searched at once, scam-checked and scored -> tracker sheet, cover-letter drafts, WhatsApp alert.",
    "build": build,
}
