"""Internship & job finder: a query and/or a resume -> live openings from 8 sources at once -> filtered and scored
in parallel -> report, tracker sheet, cover-letter drafts and a WhatsApp summary – no approval step.

Built like ``lead_research`` (same ``need`` / ``agent_node`` helpers, tools from ``tool_needs``), plus code steps
(``builder.templates.job_finder_steps``) for what needs no AI:

* The request comes as a Query field ("Gen AI jobs in Noida, 10 LPA+") and/or the resume – attached with the run
  (only the steps right after the input get the file) or in the workflow's knowledge base, so a daily schedule
  works. The query wins over the fields, the fields over the resume.
* The Profile Builder writes the PROFILE block every later step reads: roles, skills, Home and the cities a commute
  away, level, the title words above it and 6-8 search phrases. Beside it, Seen Jobs reads the tracker's Apply URLs.
* Eight search lanes run side by side, one source each (JobSpy split per site, Startup Jobs, Job Scout, LinkedIn,
  two open-web lanes for Internshala / Unstop / Wellfound / Cutshort), each making its searches together in one
  turn (LinkedIn one call at a time – it answers a burst with HTTP 429). Each has a time budget
  (``tools.time_budget_seconds``): when it runs out the lane answers with what it found, so the join never waits
  long on a slow source and nothing found is lost. A lane that fails is left out; the join goes on with the rest.
* Lanes answer in JSON lines. Code Filter merges duplicates and drops old, closed, fee-asking, wrong-level and
  already-tracked jobs, keeps the 100 most relevant and hands each Matcher its own batch (``routed``); four
  Matchers score side by side; Rank keeps every job scoring 50+, nearest first, the top ``Target`` (25) as matches.
* Contact Finder (time-boxed) and Report Writer (skill gaps, cover letters) work on the top matches; Report puts
  it all together in code. Then, without asking: the tracker (every 50+ job, the extra ones as "Extra"), Gmail
  drafts (saved, never sent) and the WhatsApp summary – which, like any message to someone, still asks first.
* While it runs, the steps' "▸ " lines (what each found, resume tips) show live on the share page.

    in -> {Profile Builder, Seen Jobs}
    Profile Builder -> {8 lanes} -> join (+ Seen Jobs) -> Code Filter (+ profile) -> {Matcher ×4} -> join -> Rank
       (+ Code Filter) -> Contact Finder (+ profile) -> Report Writer (+ profile, + Rank) -> Report (+ Rank, + contacts)
       -> {Tracker Saver, Draft Saver, WhatsApp Notifier (+ profile)} -> output (+ Report)
"""
from __future__ import annotations

import builder.templates.job_finder_steps  # noqa: F401  (registers the code steps)
from builder.templates.lead_research import (
    FIRECRAWL, JOB_SCOUT, JOBSPY, LINKEDIN, STARTUP_JOBS, TAVILY, _llm, agent_node, need,
)

SHEETS = ("Google Sheets", ["xing5/mcp-google-sheets"])
GMAIL = ("Gmail", ["jimsimoy/gmail-mcp"])
WHATSAPP = ("WhatsApp", ["lharries/whatsapp-mcp"])

TRACKER = "Internship Tracker"
TRACKER_COLUMNS = (
    "Date found | Company | Role | Location | Type | Pay | Score | Deadline | Apply URL | Status | Found via | Contact | "
    "Contact link"
)
# The column an older tracker (before contacts) ends at, and the ones it gets added.
OLD_LAST, NEW_COLUMNS = "K", ["Contact", "Contact link"]
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
    "given), url (the post's own link), requirements (the post's OWN words for skills and eligibility – degree, "
    "batch / graduation year, years of experience – at most 30 words, never your summary), source (the system and "
    "the site, e.g. \"JobSpy (Naukri)\", \"LinkedIn\", \"Tavily (Internshala)\"). List EVERY job the tools "
    "returned – later steps drop duplicates, old posts, wrong levels and score the fit – leaving out only a job in "
    "another country that is not remote-open to the Home country (never a US-only or visa-needed role for a "
    "candidate in India) and a title clearly not one of the Roles (e.g. sales for a developer). Never a top few. "
    "Never invent a company, role, pay, date or URL – what you did not read in a tool "
    "result does not exist. If a source fails, add one line after the objects saying which. Last line: \"" + NOTE +
    "<n> jobs on <the sites you searched>\" (n = your objects; 0 when none)."
)

# Each lane gives up searching after this and answers with what it has; a call waits at most ``timeout``.
LANE = dict(max_calls=8, timeout=60, time_budget=75)


def _lane(name: str, goal: str, instructions: str, needs: list[dict], *, time_budget: float, **tools) -> dict:
    # A JSON line per job: 100+ jobs need the room, or the answer is cut off mid-list.
    return dict(name=name, role="job search researcher", goal=goal, instructions=instructions + JOB_RULES,
                needs=needs, time_budget=time_budget, max_output_tokens=16000, **tools)


def _jobspy(name: str, sites: str, extra: str = "") -> dict:
    return _lane(
        name, f"Find live openings on {name.split(': ')[-1]} that fit the profile.",
        SEARCH + TOGETHER + f"JobSpy search_jobs with site_name {sites} (never linkedin – another step searches it), "
        "results_wanted 50, country_indeed \"india\" for Indian places (the country's name otherwise): the first, "
        "second and third Search phrase at Home with distance 30 (it reaches the Nearby cities), and the first "
        "phrase remote (is_remote true, location = the Home country) – 4 searches. Each with hours_old = Posted "
        "within × 24. job_type: for full-time NEVER pass job_type at all – \"full-time\" is rejected with an error; "
        "for internships job_type \"internship\" and no hours_old (Indeed can't take both). " + extra,
        [need(JOBSPY, ["search_jobs"])], **LANE,
    )


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
        "WhatsApp: <the WhatsApp number field, digits with country code, or none>\n"
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

SEEN = dict(
    name="Seen Jobs",
    role="tracker reader",
    goal=f"List the Apply URLs already in the \"{TRACKER}\" sheet, so they aren't found again.",
    instructions=(
        f"search_spreadsheets with query \"{TRACKER}\" – take the spreadsheet titled exactly \"{TRACKER}\"; then "
        "list_sheets and get_sheet_data for its first sheet. Answer with the line SEEN, then every Apply URL in "
        "column I, one per line, nothing else. No such sheet, no Sheets tools or an error: answer \"SEEN\" and on the "
        "next line \"none\"."
    ),
    needs=[need(SHEETS, ["search_spreadsheets", "list_sheets", "get_sheet_data"])],
    max_calls=4, timeout=30, time_budget=40, runs_without_needs=True,
)

LANES = [
    _jobspy("Job Boards: Indeed", "[\"indeed\"]"),
    _jobspy("Job Boards: Naukri", "[\"naukri\"]"),
    _jobspy("Job Boards: Glassdoor + Google", "[\"glassdoor\", \"google\"]",
            "Each also with google_search_term \"<phrase> jobs near <place> since <Posted within> days\". "),
    _lane(
        "Startup Jobs", "Find live startup openings that fit the profile.",
        SEARCH + TOGETHER + "Startup Jobs search_jobs, one per Search phrase 1-5 (5 searches): q = the phrase "
        "without its skill words (\"Generative AI Engineer\", not \"Generative AI Engineer Python\"), country \"IN\" "
        "(or the Home country's code), employment_type \"internship\" or \"full-time\", posted_after = Posted within "
        "days back but at most 13 days back (the free API only covers the last 14 days), limit 50. ",
        [need(STARTUP_JOBS, ["search_jobs"])], max_calls=6, timeout=40, time_budget=60,
    ),
    _lane(
        "Job Scout", "Find openings on company career sites (Greenhouse, Lever, Ashby) that fit the profile.",
        SEARCH + TOGETHER + "Job Scout search_jobs: query = Search phrase 1, 2 and 3 with location = Home (3 "
        "searches), and phrase 1 with remoteOnly true; postedAfter = Posted within days back, limit 50. ",
        [need(JOB_SCOUT, ["search_jobs"])], max_calls=5, timeout=40, time_budget=60,
    ),
    _lane(
        "LinkedIn", "Find live LinkedIn openings that fit the profile.",
        "LinkedIn rate-limits fast or parallel searches, so make ONE call per turn. " + SEARCH + "search_jobs in this "
        "order, as many as time allows: 1) Search phrase 1 at Home, work_type \"on_site,hybrid\"; 2) phrase 2 at the "
        "biggest Nearby city (Home again if none), same work_type; 3) phrase 1, location = the Home country, "
        "work_type \"remote\"; 4) phrase 3 at Home; 5) phrase 4 at Home. Each with job_type \"internship\" for "
        "internships or \"full_time\", experience_level \"internship\" for internships, \"entry\" for a fresher, "
        "\"entry,associate\" for junior, \"associate,mid_senior\" for mid, date_posted \"past_week\" when Posted "
        "within is 7 or less (\"past_month\" otherwise), max_pages 1. Never a title with a Skip titles word; jobs not "
        "in promoted_job_ids first (promoted ones are often senior). get_job_details only for at most 3 jobs whose "
        "requirements you can't tell. If LinkedIn answers with a login or rate-limit error, stop calling it and "
        "answer with what you have. ",
        [need(LINKEDIN, ["search_jobs", "get_job_details"])],
        # One at a time: LinkedIn answers parallel searches with HTTP 429 and drops the session.
        max_calls=8, timeout=60, time_budget=110, side_by_side=False,
    ),
    _lane(
        "Web: Internshala + Unstop", "Find openings on Internshala and Unstop, which have no job-board connector.",
        SEARCH + TOGETHER + "Tavily search (or Firecrawl search), one site per search, within Posted within days: "
        "\"<Search phrase 1> <Home> site:internshala.com\", \"<phrase 2> <Region> site:internshala.com\", \"<phrase "
        "1> <Home> site:unstop.com\", \"<phrase 2> work from home site:unstop.com\". A result page that lists many "
        "jobs is not a job: then open at most 4 promising pages with Tavily extract or Firecrawl scrape, together in "
        "one turn, and take the jobs from them. ",
        [need(TAVILY, ["tavily_search", "tavily_extract"]), need(FIRECRAWL, ["firecrawl_search", "firecrawl_scrape"])],
        max_calls=8, timeout=45, time_budget=80,
    ),
    _lane(
        "Web: Wellfound + Cutshort", "Find openings on Wellfound, Cutshort, Instahyre and company career pages.",
        SEARCH + TOGETHER + "Tavily search (or Firecrawl search), one site per search, within Posted within days: "
        "\"<Search phrase 1> <Region> site:wellfound.com\", \"<phrase 1> <Home> site:cutshort.io\", \"<phrase 2> "
        "<Region> site:instahyre.com\", \"<phrase 1> <Region> site:naukri.com OR site:foundit.in\", \"<phrase 2> "
        "<biggest Nearby city> careers\". A result page that lists many jobs is not a job: then open at most 4 "
        "promising pages with Tavily extract or Firecrawl scrape, together in one turn, and take the jobs from them. ",
        [need(TAVILY, ["tavily_search", "tavily_extract"]), need(FIRECRAWL, ["firecrawl_search", "firecrawl_scrape"])],
        max_calls=8, timeout=45, time_budget=80,
    ),
]

MATCHER = dict(
    role="job fit scorer",
    goal="Score each job in this batch against the candidate's profile.",
    instructions=(
        "Your input is the PROFILE block and a batch of jobs, one JSON object per line – or \"NO JOBS\": then answer "
        "only NONE. Score EVERY job 0-100: Skills 40 (how many of the post's required skills are in the profile's "
        "Skills or Projects), Eligibility 25 (degree, graduation year / batch, experience – 25 when the minimum years "
        "asked is at most the profile's Experience, 12 when it is up to 1 year more, 0 if the post rules the "
        "candidate out), Location 15 (15 at Home, 13 in a Nearby city, 10 remote and open to the Home country, 8 "
        "another city the Locations name, 3 elsewhere in the Home country), Pay 10 (at or above Min pay; 5 if not "
        "stated), Freshness 10 (posted in the last 7 days). A job the post rules the candidate out of (wrong batch, "
        "needs 2+ years for a fresher, more than Experience + 1 years, a Skip titles word in the title, in another "
        "country and not remote-open to the Home country) scores 0. Answer with one JSON object per job, one per line, "
        "in the batch's order, nothing else: {\"id\": \"<the job's id>\", \"score\": <0-100>, \"why\": \"<the post's "
        "own words it matched, quoted, e.g. \\\"React, Node.js\\\", \\\"2026 batch\\\" – at most 20 words>\", "
        "\"missing\": \"<what the post asks that the profile lacks, or empty>\"}. Never invent a requirement."
    ),
    max_output_tokens=4000,
)

CONTACTS = dict(
    name="Contact Finder",
    role="recruiter contact researcher",
    goal="Find the recruiters and published hiring contacts for the best matches.",
    instructions=(
        "Your input is the PROFILE block and the top matches. For the 8 best companies (scoring 60 or more), look in "
        "three places. " + TOGETHER.replace("searches", "lookups of each kind") + "1) the post itself: Firecrawl "
        "scrape the Apply URL of at most 3 posts that may name a recruiter or an email; 2) LinkedIn search_people with "
        "keywords \"recruiter <Company>\" or \"talent acquisition <Company>\" and location = the profile's Home city "
        "(at most 2 searches – LinkedIn rate-limits; skip it after a login or rate-limit error) – keep up to 2 people "
        "per company whose title says recruiter, talent acquisition, HR or the hiring manager of the role's team; 3) "
        "the company's careers or contact page: Tavily search or Firecrawl search \"<Company> careers email\" (at "
        "most 4) – an address printed there such as careers@ or hr@. Answer with one JSON object per contact, one per "
        "line, nothing before them: {\"company\", \"role\", \"name\", \"title\", \"email\", \"link\", \"source\"} – "
        "email = only an address a page printed (never built from a name pattern, never a personal address or "
        "phone); link = the person's LinkedIn profile URL or the page; a company with nothing found gets one object "
        "with name \"none found\". Never invent a person. Last line: \"" + NOTE + "Found <p> recruiters and <e> "
        "hiring emails for <c> companies\"."
    ),
    needs=[
        need(LINKEDIN, ["search_people"]),
        need(FIRECRAWL, ["firecrawl_scrape", "firecrawl_search"]),
        need(TAVILY, ["tavily_search"]),
    ],
    max_calls=10, timeout=25, time_budget=60,
)

WRITER = dict(
    name="Report Writer",
    role="career report writer",
    goal="Write the skill gaps and a cover letter for each top match.",
    instructions=(
        "Your input is the PROFILE block, the top matches (best first) and the Contact Finder's contacts (JSON, one "
        "per line). The matches table is added to the report by another step – don't repeat it. Write in Markdown, "
        "exactly these two parts:\n"
        "## Skill gaps\n"
        "At most 5 bullets: a skill asked by several matches that the profile lacks, how many asked for it, and one "
        "concrete way to learn or show it (a small project idea). \"None\" if there are none.\n"
        "## Cover letters\n"
        "For each match scoring 70 or more, best first, at most 5: a heading \"### <Company> – <Role>\", a line "
        "\"To: <the contact's email from the Contact Finder, otherwise the profile's Email>\", a line \"Subject: Application "
        "for <Role> – <Name>\", then a cover letter of at most 150 words – \"Dear <contact's name>\" when you have one "
        "– that names the role, links ONE real project or skill from the profile to ONE quoted requirement of the "
        "post, and asks for a conversation. Then \"Resume tips:\" with 2 bullets – what to move up or reword for this "
        "post. Never claim a skill, grade or experience the profile does not have. If no match scores 70, write \"No "
        "match scored 70 or more – no cover letters.\""
    ),
    max_output_tokens=6000,
)

TRACKER_SAVER = dict(
    name="Tracker Saver",
    role="tracker sheet keeper",
    goal=f"Add the report's matches the student's \"{TRACKER}\" sheet doesn't have yet.",
    instructions=(
        "Your input is the report; its Matches and More matches tables hold the jobs. Use exactly these calls:\n"
        f"1) search_spreadsheets with query \"{TRACKER}\" – take the spreadsheet titled exactly \"{TRACKER}\". If there is "
        f"none: create_spreadsheet with title \"{TRACKER}\", then list_sheets for its first sheet's name, then "
        "update_cells on that sheet, range A1:M1, data [[" + ", ".join(f'"{c}"' for c in TRACKER_COLUMNS.split(" | ")) + "]].\n"
        "2) list_sheets (if you have not) and get_sheet_data for the first sheet – note every Apply URL already in "
        "column I and the number of rows that have data, header included (N). If its header row ends at column "
        f"{OLD_LAST} (an older tracker), update_cells range L1:M1, data [[" + ", ".join(f'"{c}"' for c in NEW_COLUMNS) + "]].\n"
        "3) The new jobs are the rows of both tables whose Apply URL is not in the sheet. If there are none, answer "
        "\"Tracker: no new jobs – https://docs.google.com/spreadsheets/d/<id>\" and stop.\n"
        "4) ONE update_cells on the first sheet for ALL k new jobs, range A<N+1>:M<N+k>, one row each: today's date "
        "(YYYY-MM-DD), Company, Role, Location, Type, Pay, Score, Deadline, Apply URL, Status (\"New\" for a Matches "
        "row, \"Extra\" for a More matches row), Found via, Contact, Contact link – copied from the table, never "
        "changed.\n"
        "Then answer with ONLY: \"Tracker: <k> new jobs added – https://docs.google.com/spreadsheets/d/<id>\". Never say "
        "rows were added unless update_cells succeeded – on an error, answer with the error."
    ),
    needs=[need(SHEETS, ["search_spreadsheets", "create_spreadsheet", "list_sheets", "get_sheet_data", "update_cells"],
                required=True)],
    max_calls=7, timeout=60, max_output_tokens=12000,
)

DRAFT_SAVER = dict(
    name="Draft Saver",
    role="email draft keeper",
    goal="Save each cover letter as a Gmail draft – never send anything.",
    instructions=(
        "Your input is the report; its Cover letters part holds the letters. If it has none, answer \"Gmail: "
        "no cover letters to save.\" and stop. If you have no Gmail tools, answer \"Gmail is not connected – drafts "
        "skipped.\" and stop. Otherwise call get_profile once for the student's own address, then create_draft once per "
        "letter: to = the letter's To address ONLY when it is a real email (has an @); when it says none, is empty or "
        "is anything else, to = the student's own address from get_profile – never the word \"none\" (they forward "
        "it or paste it into the application form); subject = its Subject line; body_text = the letter exactly as written "
        "(not the resume tips). Never send. Then answer with ONLY: \"Gmail: <n> drafts saved\" and, on the next lines, "
        "<Company – Role> for each. On an error, answer with the error."
    ),
    needs=[need(GMAIL, ["get_profile", "create_draft"])],
    max_calls=7, timeout=60, runs_without_needs=True,
)

NOTIFIER = dict(
    name="WhatsApp Notifier",
    role="job alert sender",
    goal="Send the student one short WhatsApp message with today's best matches.",
    instructions=(
        "Your input is the PROFILE block and the report (the savers run beside you). If the profile's "
        "WhatsApp line is empty or none, answer \"WhatsApp: no number given – skipped.\" and stop. If you have no WhatsApp tools, "
        "answer \"WhatsApp is not connected – skipped.\" and stop. Otherwise call send_message once, recipient = the "
        "WhatsApp number exactly as the profile gives it (digits only, with country code) – never a number from "
        "anywhere else – message = at most 9 lines: \"🎯 <k> job matches\" "
        "(k = the number the report's first line starts with), then the Matches table's top 3 rows as \"<Score> · "
        "<Role> @ <Company> – <Apply URL>\" (plus \" · <Contact>\" when it has one), then \"All <k> are going into "
        f"your {TRACKER} sheet\", then \"Cover letters for the top <n> are being saved to your Gmail drafts\" when the "
        "report has cover letters. Then answer with ONLY \"WhatsApp: sent\", or the error."
    ),
    needs=[need(WHATSAPP, ["send_message"])],
    max_calls=2, timeout=60, runs_without_needs=True,
)


def _agent(node_id: str, x: int, y: int, spec: dict, **node) -> dict:
    spec = dict(spec)
    budget = spec.pop("time_budget", None)
    out = agent_node(node_id, x, y, **_llm(spec))
    if budget:
        out["draft_agent"]["config"]["tools"]["time_budget_seconds"] = budget
    return {**out, **node}


def build() -> dict:
    """The workflow to create: a ``WorkflowCreate`` body."""
    x = lambda i: 40 + i * 300  # noqa: E731
    lanes = [f"l{i}" for i in range(1, len(LANES) + 1)]
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
                {"name": "whatsapp", "label": "WhatsApp number for alerts", "description": "with country code, e.g. 919876543210 – empty = no message"},
            ],
        },
        agent_node("b1", x(1), 300, **PROFILE),
        _agent("sj", x(1), 560, SEEN),
        *[_agent(nid, x(2), 20 + i * 110, spec, **once) for i, (nid, spec) in enumerate(zip(lanes, LANES))],
        # "count" 1: a failed or empty source never stops the run.
        {"id": "j1", "type": "join", "label": "All jobs", "position": {"x": x(3), "y": 400},
         "join_policy": {"mode": "count", "min_required": 1}},
        {"id": "cf", "type": "code", "code": "job_filter", "label": "Code Filter", "position": {"x": x(4), "y": 400}},
        *[_agent(nid, x(5), 220 + i * 120, {**MATCHER, "name": f"Matcher {i + 1}"}, **once) for i, nid in enumerate(matchers)],
        {"id": "j2", "type": "join", "label": "All scores", "position": {"x": x(6), "y": 400},
         "join_policy": {"mode": "count", "min_required": 1}},
        {"id": "rk", "type": "code", "code": "job_rank", "label": "Rank", "position": {"x": x(7), "y": 400}},
        _agent("c1", x(8), 400, CONTACTS),
        _agent("w1", x(9), 400, WRITER),
        {"id": "rp", "type": "code", "code": "job_report", "label": "Report", "position": {"x": x(10), "y": 400}},
        # No approval before these (the person chose "auto"): drafts are never sent, the sheet is their own, and
        # WhatsApp – a message to someone – still asks first by itself.
        _agent("s1", x(11), 220, TRACKER_SAVER),
        _agent("s2", x(11), 400, DRAFT_SAVER),
        _agent("wa", x(11), 580, NOTIFIER),
        {"id": "out", "type": "output", "label": "Job matches", "position": {"x": x(12), "y": 400},
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
        ("rk", "c1"), ("b1", "c1"),
        ("rk", "w1"), ("b1", "w1"), ("c1", "w1"),
        ("rk", "rp"), ("c1", "rp"), ("w1", "rp"),
        ("rp", "s1"), ("rp", "s2"), ("rp", "wa"), ("b1", "wa"),
        # The output gets the report and what each save did.
        ("rp", "out"), ("s1", "out"), ("s2", "out"), ("wa", "out"),
    ]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(lines)]
    return {
        "name": "Internship & job finder",
        "description": (
            "Write what you're looking for and/or attach your resume (📎) and run it – every field is optional and "
            "is read from the resume when empty (or add the resume to the workflow's knowledge base for a daily "
            "schedule). Searches 8 sources at once – Indeed, Naukri, Glassdoor, Google Jobs, Startup Jobs, company "
            "career sites, LinkedIn, Internshala, Unstop, Wellfound and Cutshort – in your city first, then the "
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
    "summary": "Query or resume -> 8 job sources searched at once, scam-checked and scored -> tracker sheet, cover-letter drafts, WhatsApp alert.",
    "build": build,
}
