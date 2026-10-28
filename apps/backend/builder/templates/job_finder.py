"""Internship & job finder: a student's resume -> live openings -> scam-checked, scored matches -> tracker sheet,
cover-letter drafts and a WhatsApp summary.

Built like ``lead_research`` (same ``need`` / ``agent_node`` helpers, tools from ``tool_needs``):

* The resume comes with the run (attached with the paperclip – in the app's chat or on a share link that runs with
  the student's own apps; only the Profile Builder, right after the input, gets the file) or from the workflow's
  knowledge base, so a daily schedule works without anyone attaching it. Every field is optional: what one says
  wins over the resume, an empty one is read from it.
* Three collectors search side by side (job boards, LinkedIn, the open web for Internshala / Unstop / Wellfound,
  which have no MCP server) and write one table shape; the join goes on when one of them has answered.
* The checker drops duplicates, old posts and scams before anything is scored – a student is the easy target of
  "pay a registration fee" internships.
* Nothing is written before a person approves the report: the tracker rows (only jobs the sheet doesn't have yet,
  by apply URL), the Gmail drafts (saved, never sent) and the WhatsApp message all come after the approval.

    in -> Profile Builder -> {Job Boards, LinkedIn, Web} -> join -> Job Checker (+ profile) -> Matcher (+ profile)
       -> Report Writer (+ profile) -> approval -> {Tracker Saver, Draft Saver}
       -> WhatsApp Notifier (+ profile, + approval: the report) -> output (+ approval: the report itself, + savers)
"""
from __future__ import annotations

from builder.templates.lead_research import (
    FIRECRAWL, JOB_SCOUT, JOBSPY, LINKEDIN, STARTUP_JOBS, TAVILY, _llm, agent_node, need,
)

SHEETS = ("Google Sheets", ["xing5/mcp-google-sheets"])
GMAIL = ("Gmail", ["jimsimoy/gmail-mcp"])
WHATSAPP = ("WhatsApp", ["lharries/whatsapp-mcp"])

TRACKER = "Internship Tracker"
TRACKER_COLUMNS = "Date found | Company | Role | Location | Type | Pay | Score | Deadline | Apply URL | Status | Found via"


# ── Shared rules ─────────────────────────────────────────────────────────────

JOB_TABLE = "Company | Role | Location | Work type | Job type | Pay | Posted | Deadline | Apply URL | Requirements | Found via"

JOB_RULES = (
    "Answer with ONE markdown table: " + JOB_TABLE + ". Work type = on-site, remote or hybrid; Job type = "
    "internship or full-time; Pay = the stipend or salary EXACTLY as posted (e.g. \"₹15,000/month\"), empty if not "
    "given; Posted and Deadline = YYYY-MM-DD, empty if not given; Apply URL = the post's own link; Requirements = "
    "the post's OWN words for skills and eligibility (degree, batch / graduation year, years of experience), at most "
    "30 words – never your summary; Found via = the system and the site, e.g. \"JobSpy (Naukri)\", \"LinkedIn\", "
    "\"Startup Jobs\", \"Job Scout (Greenhouse)\", \"Tavily (Internshala)\". Follow the profile: skip roles above its "
    "Experience (senior, lead, 3+ years for a fresher), the Type it did not ask for, its Exclude list, and posts older "
    "than 30 days. Never invent a company, role, pay, date or URL – what you did not read in a tool result does not "
    "exist. If a source fails or is not connected, use the others and say which in one line under the table. If "
    "nothing fits, answer \"No jobs found.\" and nothing else."
)


# ── Steps ────────────────────────────────────────────────────────────────────

PROFILE = dict(
    name="Profile Builder",
    role="career profile planner",
    goal="Work out who the student is and what to search for, from the resume and the run's fields.",
    instructions=(
        "The resume is the file attached to the request (<attached_file>), or – when nothing is attached – it is in "
        "the workflow's knowledge base: search it (\"resume\", \"education\", \"skills\", \"projects\"). A run field that is filled in wins over the resume; an empty one is "
        "taken from it. If there is no resume and neither Roles nor Skills is given, answer only: \"Attach your resume "
        "(PDF) or add it to the workflow's knowledge base – or at least fill in Roles you want.\" Start your answer "
        "with this block, exactly these lines (later steps read them):\n"
        "PROFILE\n"
        "Name: <from the resume, or empty>\n"
        "Email: <from the resume, or empty>\n"
        "Education: <degree, branch, college, graduation year>\n"
        "Skills: <comma-separated, strongest first, only what the resume or the fields say>\n"
        "Projects: <at most 3, a few words each>\n"
        "Roles: <comma-separated>\n"
        "Locations: <comma-separated cities, Remote, or Any>\n"
        "Type: <internship, full-time or both – internship if not given>\n"
        "Experience: <fresher, or years – fresher if not given>\n"
        "Min pay: <as given, or Any>\n"
        "Exclude: <comma-separated – always include unpaid and roles asking for a fee>\n"
        "WhatsApp: <the WhatsApp number field, digits with country code, or none>\n"
        "Then, in at most 6 bullets: for each role, 3-4 search phrases job boards use (\"SDE Intern\", \"Software "
        "Engineering Intern\", \"Backend Developer Intern\"; for full-time also \"Graduate Engineer Trainee\", \"Associate "
        "Software Engineer\"). Never name companies – the collectors find them."
    ),
)

BOARDS = dict(
    name="Job Boards Collector",
    role="job board researcher",
    goal="Find live openings on job boards that fit the profile.",
    instructions=(
        "Search with the profile's phrases, in each of its Locations (Remote as a remote search). Use EVERY source you "
        "have at least once: JobSpy search_jobs with site_name [\"indeed\", \"naukri\", \"glassdoor\", \"google\"] (never "
        "linkedin – another step searches it), country_indeed \"india\" for Indian cities (the country's name "
        "otherwise), hours_old 720, results_wanted 15, job_type \"internship\" for internships; Startup Jobs search_jobs "
        "with q, country \"IN\" (or the location's code), employment_type \"internship\" or \"full-time\" and "
        "posted_after 30 days back; Job Scout search_jobs with query, location, remoteOnly for Remote and postedAfter 30 "
        "days back. At most 8 searches; aim for 10-25 jobs. " + JOB_RULES
    ),
    needs=[
        need(JOBSPY, ["search_jobs"]),
        need(STARTUP_JOBS, ["search_jobs", "get_job"]),
        need(JOB_SCOUT, ["search_jobs", "list_company_jobs"]),
    ],
    max_calls=10, timeout=150,
)

LINKEDIN_JOBS = dict(
    name="LinkedIn Collector",
    role="LinkedIn job researcher",
    goal="Find live LinkedIn openings that fit the profile.",
    instructions=(
        "Use LinkedIn search_jobs with keywords = one of the profile's phrases, location = one of its Locations, "
        "date_posted \"past_month\", experience_level \"internship\" for internships and \"entry\" for fresher full-time "
        "roles, work_type \"remote\" for Remote, max_pages 1. At most 3 searches (each takes about a minute), then "
        "get_job_details for at most 6 of the best-looking jobs to read their requirements and pay. " + JOB_RULES
    ),
    needs=[need(LINKEDIN, ["search_jobs", "get_job_details"])],
    max_calls=9, timeout=150,
)

WEB = dict(
    name="Web Collector",
    role="internship web researcher",
    goal="Find openings on sites with no job-board connector: Internshala, Unstop, Wellfound, company career pages.",
    instructions=(
        "Search the open web with the profile's phrases and Locations, one site at a time: Tavily search (or Firecrawl "
        "search) with \"site:internshala.com\", \"site:unstop.com\", \"site:wellfound.com\" and \"careers\" pages of "
        "companies hiring freshers, last 30 days. A result page that lists many jobs is not a job: open at most 4 "
        "promising pages with Tavily extract or Firecrawl scrape and take the jobs from them. Found via = \"Tavily "
        "(<site>)\" or \"Firecrawl (<site>)\". At most 8 calls. " + JOB_RULES
    ),
    needs=[
        need(TAVILY, ["tavily_search", "tavily_extract"]),
        need(FIRECRAWL, ["firecrawl_search", "firecrawl_scrape"]),
    ],
    timeout=120,
)

CHECKER = dict(
    name="Job Checker",
    role="job post checker",
    goal="Keep each real, recent job once; drop duplicates, stale posts and scams with the reason.",
    instructions=(
        "Your input is the PROFILE block and the collectors' tables. 1) Merge duplicates – the same company and role "
        "from two sources is ONE row (keep the most complete one, Found via lists both). 2) Drop a job when: it asks "
        "the candidate to pay (registration, training, security or \"kit\" fee); it is unpaid when the profile's "
        "Exclude says unpaid; it has no company name or the company is a staffing agency posting for an unnamed client; "
        "it asks to apply only by WhatsApp or a personal Gmail; its Posted date is more than 30 days ago or its Deadline "
        "has passed; it has no Apply URL. 3) For at most 3 kept jobs whose Requirements cell is empty, read the post with "
        "Firecrawl scrape and fill it in from the post's own words. Answer with the kept jobs as ONE markdown table, "
        "the same columns as your input, then a heading \"Dropped\" and one line per dropped job: <Company – Role>: "
        "<reason>. Never add a job that was not in your input."
    ),
    needs=[need(FIRECRAWL, ["firecrawl_scrape"])],
    max_calls=3, timeout=60,
)

MATCHER = dict(
    name="Matcher",
    role="job fit scorer",
    goal="Score every checked job against the student's profile and keep the best 15.",
    instructions=(
        "Your input is the PROFILE block and the Job Checker's table. Score each job 0-100: Skills 40 (how many of the "
        "post's required skills are in the profile's Skills or Projects), Eligibility 25 (degree, graduation year / "
        "batch, experience – 0 if the post rules the student out), Location 15 (in Locations, or remote when Remote is "
        "asked), Pay 10 (at or above Min pay; 5 if not stated), Freshness 10 (posted in the last 7 days). A job the "
        "post rules the student out of (wrong batch, needs 2+ years for a fresher) goes, whatever its score. Keep the "
        "best 15, highest first. Answer with ONLY one markdown table: Score | Company | Role | Location | Type | Pay | "
        "Posted | Deadline | Apply URL | Why it fits | Missing skills | Found via. Why it fits QUOTES the post's words "
        "it matched (\"React, Node.js\", \"2026 batch\"); Missing skills = what the post asks that the profile lacks, "
        "or empty. Never invent a requirement."
    ),
)

WRITER = dict(
    name="Report Writer",
    role="career report writer",
    goal="Write one report: the matches, the skill gaps, and a cover letter for each top match.",
    instructions=(
        "Your input is the PROFILE block and the Matcher's table. Write in Markdown, exactly these parts:\n"
        "# Job matches – <today's date>\n"
        "One line: how many matches, how many internships and full-time.\n"
        "## Matches\n"
        "The Matcher's table exactly as you received it (later steps copy its rows to a sheet).\n"
        "## Skill gaps\n"
        "At most 5 bullets: a skill asked by several matches that the profile lacks, how many asked for it, and one "
        "concrete way to learn or show it (a small project idea). \"None\" if there are none.\n"
        "## Cover letters\n"
        "For each match scoring 70 or more, best first, at most 5: a heading \"### <Company> – <Role>\", a line "
        "\"To: <the recruiter's email if the post gave one, otherwise none>\", a line \"Subject: Application for <Role> "
        "– <Name>\", then a cover letter of at most 150 words that names the role, links ONE real project or skill from "
        "the profile to ONE quoted requirement of the post, and asks for a conversation. Then \"Resume tips:\" with 2 "
        "bullets – what to move up or reword for this post. Never claim a skill, grade or experience the profile does "
        "not have. If no match scores 70, say \"No match scored 70 or more – no cover letters.\""
    ),
    max_output_tokens=8000,
)

TRACKER_SAVER = dict(
    name="Tracker Saver",
    role="tracker sheet keeper",
    goal=f"Add the approved matches the student's \"{TRACKER}\" sheet doesn't have yet.",
    instructions=(
        "Your input is the approved report; its Matches table holds the jobs. Use exactly these calls:\n"
        f"1) search_spreadsheets with query \"{TRACKER}\" – take the spreadsheet titled exactly \"{TRACKER}\". If there is "
        f"none: create_spreadsheet with title \"{TRACKER}\", then list_sheets for its first sheet's name, then "
        "update_cells on that sheet, range A1:K1, data [[" + ", ".join(f'"{c}"' for c in TRACKER_COLUMNS.split(" | ")) + "]].\n"
        "2) list_sheets (if you have not) and get_sheet_data for the first sheet – note every Apply URL already in "
        "column I and the number of rows that have data, header included (N).\n"
        "3) The new jobs are the Matches rows whose Apply URL is not in the sheet. If there are none, answer \"Tracker: "
        "no new jobs – https://docs.google.com/spreadsheets/d/<id>\" and stop.\n"
        "4) update_cells on the first sheet, range A<N+1>:K<N+k> for k new jobs, one row each: today's date "
        "(YYYY-MM-DD), Company, Role, Location, Type, Pay, Score, Deadline, Apply URL, \"New\", Found via – copied from "
        "the table, never changed.\n"
        "Then answer with ONLY: \"Tracker: <k> new jobs added – https://docs.google.com/spreadsheets/d/<id>\". Never say "
        "rows were added unless update_cells succeeded – on an error, answer with the error."
    ),
    needs=[need(SHEETS, ["search_spreadsheets", "create_spreadsheet", "list_sheets", "get_sheet_data", "update_cells"],
                required=True)],
    max_calls=7, timeout=60,
)

DRAFT_SAVER = dict(
    name="Draft Saver",
    role="email draft keeper",
    goal="Save each approved cover letter as a Gmail draft – never send anything.",
    instructions=(
        "Your input is the approved report; its Cover letters part holds the letters. If it has none, answer \"Gmail: "
        "no cover letters to save.\" and stop. If you have no Gmail tools, answer \"Gmail is not connected – drafts "
        "skipped.\" and stop. Otherwise call get_profile once for the student's own address, then create_draft once per "
        "letter: to = the letter's To address, or the student's own address when it is none (they forward it or "
        "paste it into the application form); subject = its Subject line; body_text = the letter exactly as written "
        "(not the resume tips). Never send. Then answer with ONLY: \"Gmail: <n> drafts saved\" and, on the next lines, "
        "<Company – Role> for each. On an error, answer with the error."
    ),
    needs=[need(GMAIL, ["get_profile", "create_draft"])],
    max_calls=7, timeout=60,
)

NOTIFIER = dict(
    name="WhatsApp Notifier",
    role="job alert sender",
    goal="Send the student one short WhatsApp message with today's best matches.",
    instructions=(
        "Your input is the PROFILE block, the approved report and the savers' answers (the tracker link, the "
        "drafts). If the profile's "
        "WhatsApp line is none, answer \"WhatsApp: no number given – skipped.\" and stop. If you have no WhatsApp tools, "
        "answer \"WhatsApp is not connected – skipped.\" and stop. Otherwise call send_message once, recipient = the "
        "WhatsApp number (digits only, with country code), message = at most 8 lines: \"🎯 <k> job matches today\" "
        "(k = rows in the report's Matches table), then its top 3 rows as \"<Score> · <Role> @ <Company> – <Apply "
        "URL>\", then the tracker link from the Tracker Saver's answer, then \"<n> cover letters are in your Gmail "
        "drafts\" when the Draft Saver saved any. Then answer with ONLY \"WhatsApp: sent\", or the error."
    ),
    needs=[need(WHATSAPP, ["send_message"])],
    max_calls=2, timeout=60,
)


def build() -> dict:
    """The workflow to create: a ``WorkflowCreate`` body."""
    x = lambda i: 40 + i * 300  # noqa: E731
    lanes = [("r1", BOARDS), ("r2", LINKEDIN_JOBS), ("r3", WEB)]
    nodes = [
        {
            # Attach the resume with the run (📎); the fields only narrow or override what it says.
            "id": "in", "type": "input", "label": "Your resume + what you're looking for", "position": {"x": x(0), "y": 300},
            "variables": [
                # All optional: the resume (attached, or in the knowledge base) fills in what's empty.
                {"name": "roles", "label": "Roles you want", "description": "e.g. SDE Intern, Data Analyst – empty = from your resume"},
                {"name": "locations", "label": "Locations", "description": "e.g. Bangalore, Pune, Remote – empty = anywhere"},
                {"name": "job_type", "label": "Internship or full-time", "description": "internship, full-time or both – empty = internship"},
                {"name": "experience", "label": "Experience", "description": "e.g. fresher, 1 year – empty = fresher"},
                {"name": "min_pay", "label": "Minimum stipend / salary", "description": "e.g. ₹10,000/month – empty = any"},
                {"name": "skills", "label": "Skills", "description": "e.g. Python, React, SQL – empty = from your resume"},
                {"name": "exclude", "label": "Never show", "description": "e.g. sales roles, these companies"},
                {"name": "whatsapp", "label": "WhatsApp number for alerts", "description": "with country code, e.g. 919876543210 – empty = no message"},
            ],
        },
        agent_node("b1", x(1), 300, **PROFILE),
        *[agent_node(nid, x(2), 80 + i * 220, **_llm(spec)) for i, (nid, spec) in enumerate(lanes)],
        # "count" 1: one failed or empty source never stops the run; the join still waits for all three.
        {"id": "j1", "type": "join", "label": "All jobs", "position": {"x": x(3), "y": 300},
         "join_policy": {"mode": "count", "min_required": 1}},
        agent_node("k1", x(4), 300, **_llm(CHECKER)),
        agent_node("m1", x(5), 300, **_llm(MATCHER)),
        agent_node("w1", x(6), 300, **_llm(WRITER)),
        {"id": "ap", "type": "human_approval", "label": "Review the matches", "position": {"x": x(7), "y": 300},
         "approval_message": "Review the matches and cover letters before they're added to your tracker sheet, saved as "
                             "Gmail drafts and sent to your WhatsApp."},
        # Approved just above, so the saves themselves don't ask again.
        agent_node("s1", x(8), 180, **_llm(TRACKER_SAVER)),
        agent_node("s2", x(8), 420, **_llm(DRAFT_SAVER)),
        agent_node("wa", x(9), 300, **_llm(NOTIFIER)),
        {"id": "out", "type": "output", "label": "Job matches", "position": {"x": x(10), "y": 300},
         "output_config": {"format": "markdown", "compose": "off"}},
    ]
    lines = [
        ("in", "b1"),
        *[("b1", nid) for nid, _ in lanes],
        *[(nid, "j1") for nid, _ in lanes],
        # The checker, matcher and writer each see the profile next to the jobs.
        ("b1", "k1"), ("j1", "k1"),
        ("b1", "m1"), ("k1", "m1"),
        ("b1", "w1"), ("m1", "w1"),
        ("w1", "ap"),
        ("ap", "s1"), ("ap", "s2"),
        ("b1", "wa"), ("ap", "wa"), ("s1", "wa"), ("s2", "wa"),
        # The output gets the report (through the approval) and what each save did.
        ("ap", "out"), ("s1", "out"), ("s2", "out"), ("wa", "out"),
    ]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(lines)]
    return {
        "name": "Internship & job finder",
        "description": (
            "Attach your resume (📎) and run it – every field is optional and is read from the resume when empty (or "
            "add the resume to the workflow's knowledge base for a daily schedule). Searches job boards, LinkedIn, "
            "Internshala, Unstop and Wellfound live for internships and fresher jobs, drops duplicates, old posts and "
            "scams, scores every job against your profile with the post's own words, writes cover letters for the best "
            f"ones and – after you approve – adds new jobs to a Google Sheet called \"{TRACKER}\", saves the letters as "
            "Gmail drafts and sends you a WhatsApp summary. Schedule it daily for fresh matches every morning."
        ),
        "nodes": nodes,
        "edges": edges,
        "config": {
            "max_run_seconds": 3600,
            "on_node_failure": "retry",
            "node_retry_count": 1,
            "node_retry_fallback": "abort",
            # Only the saves change anything, and the approval step covers them.
            "approvals": {"read": False, "edit": False, "delete": True},
        },
    }


TEMPLATE = {
    "key": "job_finder",
    "name": "Internship & job finder",
    "summary": "Resume -> live internships & fresher jobs, scam-checked and scored -> tracker sheet, cover-letter drafts, WhatsApp alert.",
    "build": build,
}
