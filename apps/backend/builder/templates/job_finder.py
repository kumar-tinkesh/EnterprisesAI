"""Internship & job finder: a student's resume -> live openings -> scam-checked, scored matches -> tracker sheet,
cover-letter drafts and a WhatsApp summary.

Built like ``lead_research`` (same ``need`` / ``agent_node`` helpers, tools from ``tool_needs``):

* The resume comes with the run (attached with the paperclip – in the app's chat or on a share link that runs with
  the student's own apps; only the Profile Builder, right after the input, gets the file) or from the workflow's
  knowledge base, so a daily schedule works without anyone attaching it. Every field is optional: what one says
  wins over the resume, an empty one is read from it.
* Three collectors search side by side (job boards, LinkedIn, the open web for Internshala / Unstop / Wellfound,
  which have no MCP server) and write one table shape; the join goes on when one of them has answered.
* The Profile Builder reads roles, skills, experience and place from the resume (an empty field), adds the cities
  a commute away (Noida -> Delhi, Gurgaon…) and the title words above the candidate's level; every collector
  builds its searches from those lines (``SEARCH``), home and nearby first, then remote – then every match
  scoring 50+ goes on, nearest first, not a top few: the tracker gets them all in one write.
* The checker drops duplicates, old posts and scams before anything is scored – a student is the easy target of
  "pay a registration fee" internships. The Contact Finder then looks for the recruiters and published hiring
  emails of the best matches (never a guessed address), which the cover letters are addressed to.
* Collectors are told to make their searches together in one turn: the agent runtime runs a turn's read-only
  calls side by side, so a lane takes about as long as its slowest search – except LinkedIn, one call at a time
  (``side_by_side`` off), since it answers a burst with HTTP 429 and drops the session.
* Nothing is written before a person approves the report: the tracker rows (only jobs the sheet doesn't have yet,
  by apply URL), the Gmail drafts (saved, never sent) and the WhatsApp summary all come after the approval, side by
  side. (No "search started" WhatsApp: a send always asks first, so it would stop the run at its start.) The
  WhatsApp and Gmail steps run without their system (``runs_without_needs``) and say they skipped, so a student
  without them can still run it.
* While it runs, the steps' "▸ " lines (what each found, resume tips) show live on the share page.

    in -> Profile Builder -> {Job Boards, LinkedIn, Web} -> join -> Job Checker (+ profile) -> Matcher (+ profile)
       -> Contact Finder (+ profile) -> Report Writer (+ profile, + matcher) -> approval
       -> {Tracker Saver, Draft Saver, WhatsApp Notifier (+ profile)} -> output (+ approval: the report, + all three)
"""
from __future__ import annotations

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


# ── Shared rules ─────────────────────────────────────────────────────────────

# Every collector builds its searches from the same profile lines, nearest places first.
SEARCH = (
    "Build EVERY search from the PROFILE block: keywords = its Search phrases (the role titles, some with the "
    "strongest skill), place = Home first, then Nearby, then Remote (other Locations after those), level = its "
    "Seniority, type = its Type, recency = its Posted within. Never search a city or country the profile does not "
    "list. "
)

JOB_TABLE = "Company | Role | Location | Work type | Job type | Pay | Posted | Deadline | Apply URL | Requirements | Found via"

JOB_RULES = (
    "Answer with ONE markdown table: " + JOB_TABLE + ". Work type = on-site, remote or hybrid; Job type = "
    "internship or full-time; Pay = the stipend or salary EXACTLY as posted (e.g. \"₹15,000/month\"), empty if not "
    "given; Posted and Deadline = YYYY-MM-DD, empty if not given; Apply URL = the post's own link; Requirements = "
    "the post's OWN words for skills and eligibility (degree, batch / graduation year, years of experience), at most "
    "30 words – never your summary; Found via = the system and the site, e.g. \"JobSpy (Naukri)\", \"LinkedIn\", "
    "\"Startup Jobs\", \"Job Scout (Greenhouse)\", \"Tavily (Internshala)\". Follow the profile: skip a title with a "
    "word from its Skip titles, a post whose minimum years asked is more than its Experience + 1 (a fresher: more "
    "than 1), the Type it did not ask for, its Exclude list, posts older than its Posted within days, and jobs "
    "outside its Home, Nearby and Locations – a job in another country counts only when it is remote AND open to "
    "people in the profile's Home country (never a US-only or visa-needed role for a candidate in India). List EVERY job that fits – no top few. Never invent "
    "a company, role, pay, date or URL – what you did not read in a tool result does not "
    "exist. If a source fails or is not connected, use the others and say which in one line under the table. If "
    "nothing fits, answer \"No jobs found.\". Then, as the LAST line, \"" + NOTE + "<n> jobs found on <the sites you "
    "searched>\" (n = your table's rows; 0 when none) – it is shown to the person while the search runs."
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
        "Home: <city, country – where the resume says they live or work now (current job, address); empty if it "
        "doesn't say>\n"
        "Nearby: <comma-separated cities a daily commute from Home, biggest job markets first (Noida -> Delhi, "
        "Gurgaon, Greater Noida, Ghaziabad, Faridabad; Pune -> Pimpri-Chinchwad, Mumbai only if under 3 hours); empty "
        "if Home is empty>\n"
        "Region: <the metro area job sites use for Home and Nearby together, e.g. \"Delhi NCR\", \"Mumbai Metropolitan "
        "Region\", \"Bengaluru\"; empty if Home is empty>\n"
        "Locations: <the Locations field when filled in; otherwise Home, Nearby and Remote (e.g. \"Noida, Delhi, "
        "Gurgaon, Remote\"); Any only when the field says Any or neither it nor the resume names a place – never "
        "add Any yourself>\n"
        "Type: <the field when filled in; otherwise internship for a student or fresher, full-time for someone with "
        "work experience>\n"
        "Experience: <the field when filled in; otherwise the resume's years of full-time work, e.g. \"2.5 years\" "
        "(internships alone = fresher)>\n"
        "Seniority: <fresher (no full-time work), junior (under 5 years) or mid (5 years or more)>\n"
        "Skip titles: <title words above the Seniority – fresher and junior: Senior, Sr, Lead, Principal, Staff, "
        "Architect, Manager, Head, Director; mid: Principal, Director, Head, VP>\n"
        "Min pay: <as given, or Any>\n"
        "Posted within: <the Posted within field in days, or 14>\n"
        "Exclude: <comma-separated – always include unpaid and roles asking for a fee>\n"
        "WhatsApp: <the WhatsApp number field, digits with country code, or none>\n"
        "Search phrases: <4-6 phrases separated by \" ; \", best first, each at most 4 words as job boards title "
        "them, from the Roles and the Experience (\"SDE Intern\", \"Backend Developer Intern\"; full-time also "
        "\"Graduate Engineer Trainee\", \"Associate Software Engineer\"); 2 of them add the strongest skill "
        "(\"Python Developer FastAPI\"); never a word from Skip titles, never \"full-time\" or a company>\n"
        "End with exactly 4 lines the person sees while the search runs: \"" + NOTE + "Looking for <first 2 Roles> in "
        "<Home and Nearby, then Remote>, posted in the last <Posted within> days (<Experience>)\", then 3 lines \"" + NOTE + "Tip: <one "
        "short, concrete tip for THIS resume – what to add, move up or reword to fit the Roles>\"."
    ),
)

BOARDS = dict(
    name="Job Boards Collector",
    role="job board researcher",
    goal="Find live openings on job boards that fit the profile.",
    instructions=(
        SEARCH + TOGETHER + "Use EVERY source you have:\n"
        "- JobSpy search_jobs (site_name [\"indeed\", \"naukri\", \"glassdoor\", \"google\"] – never linkedin, another "
        "step searches it – results_wanted 30, country_indeed \"india\" for Indian places, the country's name "
        "otherwise): 2 searches at Home with distance 30 (it reaches the Nearby cities), the first and second Search "
        "phrase; 1 at the biggest Nearby city with the first phrase; 1 remote (is_remote true, location = the Home "
        "country) with the first phrase. Each with google_search_term \"<phrase> jobs near <place> since <Posted "
        "within> days\" and hours_old = Posted within × 24 – except internships: job_type \"internship\" and no "
        "hours_old (Indeed can't take both); for full-time leave job_type out (its other values filter everything "
        "away). A search with 0 jobs gets ONE retry with a shorter phrase (e.g. \"AI Engineer\") and no hours_old.\n"
        "- Startup Jobs search_jobs: q = the first and second phrase (2 searches), country \"IN\" (or the Home "
        "country's code), employment_type \"internship\" or \"full-time\", posted_after = Posted within days back, "
        "limit 50.\n"
        "- Job Scout search_jobs: query = the first phrase, location = Home, then once more remoteOnly true; "
        "postedAfter = Posted within days back, limit 50.\n"
        "At most 10 searches in that turn; if Startup Jobs gave a next_cursor, fetch that one next page after. "
        + JOB_RULES
    ),
    needs=[
        need(JOBSPY, ["search_jobs"]),
        need(STARTUP_JOBS, ["search_jobs", "get_job"]),
        need(JOB_SCOUT, ["search_jobs", "list_company_jobs"]),
    ],
    max_calls=12, timeout=150,
)

LINKEDIN_JOBS = dict(
    name="LinkedIn Collector",
    role="LinkedIn job researcher",
    goal="Find live LinkedIn openings that fit the profile.",
    instructions=(
        "LinkedIn rate-limits fast or parallel searches, so make ONE call per turn. " + SEARCH + "At most 4 "
        "search_jobs, in this order: 1) the first Search phrase at Home, work_type \"on_site,hybrid\"; 2) the second "
        "phrase at the biggest Nearby city (Home again if none), same work_type; 3) the first phrase, location = the "
        "Home country, work_type \"remote\"; 4) only if 1-3 gave fewer than 10 jobs that fit, the third phrase at "
        "Home. Each with "
        "job_type \"internship\" for internships or \"full_time\", experience_level \"internship\" for internships, "
        "\"entry\" for a fresher, \"entry,associate\" for junior, \"associate,mid_senior\" for mid, date_posted "
        "\"past_week\" when Posted within is 7 or less (\"past_month\" otherwise), max_pages 2. Then pick from the "
        "results: never a title with a Skip titles word, jobs not in promoted_job_ids first (promoted ones are "
        "often senior), Home and Nearby before Remote – and get_job_details for at most 6 of them to read their "
        "requirements and pay. If LinkedIn answers with a login or rate-limit error, stop calling it and answer with "
        "what you have. " + JOB_RULES
    ),
    needs=[need(LINKEDIN, ["search_jobs", "get_job_details"])],
    # One at a time: LinkedIn answers parallel searches with HTTP 429 and drops the session.
    max_calls=10, timeout=150, side_by_side=False,
)

WEB = dict(
    name="Web Collector",
    role="internship web researcher",
    goal="Find openings on sites with no job-board connector: Internshala, Unstop, Wellfound, company career pages.",
    instructions=(
        SEARCH + "Search the open web, one site per search: Tavily search (or Firecrawl search) with \"<first Search "
        "phrase> <Home> site:internshala.com\", the same for site:unstop.com and site:wellfound.com, \"<first "
        "phrase> <Region> site:naukri.com OR site:foundit.in\", \"<second phrase> <biggest Nearby city> careers\", "
        "and one \"<first phrase> work from home <Home country>\" on internshala or wellfound – within Posted within "
        "days. " + TOGETHER + "A result page that lists "
        "many jobs is not a job: then open at most 5 promising pages with Tavily extract or Firecrawl scrape, together "
        "in one turn, and take the jobs from them. Found via = \"Tavily (<site>)\" or \"Firecrawl (<site>)\". At most "
        "12 calls. " + JOB_RULES
    ),
    needs=[
        need(TAVILY, ["tavily_search", "tavily_extract"]),
        need(FIRECRAWL, ["firecrawl_search", "firecrawl_scrape"]),
    ],
    max_calls=12, timeout=120,
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
        "it asks to apply only by WhatsApp or a personal Gmail; its Posted date is older than the profile's Posted within "
        "days or its Deadline has passed; it has no Apply URL. 3) For at most 3 kept jobs whose Requirements cell is empty, read the post with "
        "Firecrawl scrape and fill it in from the post's own words. Answer with the kept jobs as ONE markdown table, "
        "the same columns as your input, then a heading \"Dropped\" and one line per dropped job: <Company – Role>: "
        "<reason>. Never add a job that was not in your input. Last line: \"" + NOTE + "Checked <n> jobs: <kept> kept, "
        "<duplicates> duplicates and <scams> fee-asking or fake posts removed\"."
    ),
    needs=[need(FIRECRAWL, ["firecrawl_scrape"])],
    max_calls=3, timeout=60,
)

MATCHER = dict(
    name="Matcher",
    role="job fit scorer",
    goal="Score every checked job against the student's profile and keep every good match.",
    instructions=(
        "Your input is the PROFILE block and the Job Checker's table. Score each job 0-100: Skills 40 (how many of the "
        "post's required skills are in the profile's Skills or Projects), Eligibility 25 (degree, graduation year / "
        "batch, experience – 25 when the minimum years asked is at most the profile's Experience, 12 when it is up "
        "to 1 year more, 0 if the post rules the student out), Location 15 (15 at Home, 13 in a Nearby city, 10 "
        "remote and open to the Home country, 8 another city the Locations name, 3 elsewhere in the Home country), "
        "Pay 10 (at or above Min pay; 5 if not stated), Freshness 10 (posted in the last 7 days). A job the "
        "post rules the student out of (wrong batch, needs 2+ years for a fresher, more than Experience + 1 years, a "
        "Skip titles word in the title, in another country and not remote-open to the Home country) goes, whatever "
        "its score. Keep EVERY job scoring 50 or more – no limit – and order them nearest first: Home and Nearby "
        "jobs, then Remote, then the rest, each group highest score first. Answer with ONLY one markdown table: Score | Company | Role | Location | Type | Pay | "
        "Posted | Deadline | Apply URL | Why it fits | Missing skills | Found via. Why it fits QUOTES the post's words "
        "it matched (\"React, Node.js\", \"2026 batch\"); Missing skills = what the post asks that the profile lacks, "
        "or empty. Never invent a requirement. Last line: \"" + NOTE + "<k> matches scored 50+ – best: <Score> · <Role> @ "
        "<Company>\" (or \"" + NOTE + "No job scored 50+\")."
    ),
    max_output_tokens=8000,
)

CONTACTS = dict(
    name="Contact Finder",
    role="recruiter contact researcher",
    goal="Find the recruiters and published hiring contacts for the best matches.",
    instructions=(
        "Your input is the PROFILE block and the Matcher's table. For the jobs scoring 60 or more, best first, at most 10 "
        "companies, look in three places. " + TOGETHER.replace("searches", "lookups of each kind") + "1) the post "
        "itself: Firecrawl scrape the Apply URL of at most 4 posts that may name a recruiter or an email; 2) LinkedIn "
        "search_people with keywords \"recruiter <Company>\" or \"talent acquisition <Company>\" and location = the "
        "profile's Home city (at most 2 searches – LinkedIn rate-limits; skip it after a login or rate-limit error) – keep up to 2 people per company whose title says recruiter, talent "
        "acquisition, HR or the hiring manager of the role's team; 3) the company's careers or contact page: Tavily "
        "search or Firecrawl search \"<Company> careers email\" (at most 4) – an address printed there such as careers@ "
        "or hr@. Answer with ONLY one markdown table: Company | Role | Name | Title | Email | Contact link | Source URL. "
        "Email = only an address a page printed – never built from a name pattern, never a personal address or phone; "
        "Contact link = the person's LinkedIn profile URL or the page; one row per person or contact point. A company "
        "with nothing found gets one row with Name \"none found\". Never invent a person. Last line: \"" + NOTE + "Found "
        "<p> recruiters and <e> hiring emails for <c> companies\"."
    ),
    needs=[
        need(LINKEDIN, ["search_people"]),
        need(FIRECRAWL, ["firecrawl_scrape", "firecrawl_search"]),
        need(TAVILY, ["tavily_search"]),
    ],
    max_calls=14, timeout=90,
)

WRITER = dict(
    name="Report Writer",
    role="career report writer",
    goal="Write one report: the matches, the skill gaps, and a cover letter for each top match.",
    instructions=(
        "Your input is the PROFILE block, the Matcher's table and the Contact Finder's contacts. Write in Markdown, "
        "exactly these parts:\n"
        "# Job matches – <today's date>\n"
        "One line: how many matches, how many internships and full-time, how many near you (Home and Nearby), "
        "remote and elsewhere.\n"
        "## Matches\n"
        "EVERY row of the Matcher's table, in its order, with its columns as received plus two at the end: Contact (the "
        "best contact for that company: \"<Name> (<Title>)\" or the email, empty if none found) and Contact link (its "
        "LinkedIn URL, email or page). Later steps copy these rows to a sheet – never drop or change one.\n"
        "## Skill gaps\n"
        "At most 5 bullets: a skill asked by several matches that the profile lacks, how many asked for it, and one "
        "concrete way to learn or show it (a small project idea). \"None\" if there are none.\n"
        "## Cover letters\n"
        "For each match scoring 70 or more, best first, at most 5: a heading \"### <Company> – <Role>\", a line "
        "\"To: <the contact's email from the Contact Finder or the post, otherwise the word none>\", a line \"Subject: Application "
        "for <Role> – <Name>\", then a cover letter of at most 150 words – \"Dear <contact's name>\" when you have one – "
        "that names the role, links ONE real project or skill from "
        "the profile to ONE quoted requirement of the post, and asks for a conversation. Then \"Resume tips:\" with 2 "
        "bullets – what to move up or reword for this post. Never claim a skill, grade or experience the profile does "
        "not have. If no match scores 70, say \"No match scored 70 or more – no cover letters.\""
    ),
    max_output_tokens=12000,
)

TRACKER_SAVER = dict(
    name="Tracker Saver",
    role="tracker sheet keeper",
    goal=f"Add the approved matches the student's \"{TRACKER}\" sheet doesn't have yet.",
    instructions=(
        "Your input is the approved report; its Matches table holds the jobs. Use exactly these calls:\n"
        f"1) search_spreadsheets with query \"{TRACKER}\" – take the spreadsheet titled exactly \"{TRACKER}\". If there is "
        f"none: create_spreadsheet with title \"{TRACKER}\", then list_sheets for its first sheet's name, then "
        "update_cells on that sheet, range A1:M1, data [[" + ", ".join(f'"{c}"' for c in TRACKER_COLUMNS.split(" | ")) + "]].\n"
        "2) list_sheets (if you have not) and get_sheet_data for the first sheet – note every Apply URL already in "
        "column I and the number of rows that have data, header included (N). If its header row ends at column "
        f"{OLD_LAST} (an older tracker), update_cells range L1:M1, data [[" + ", ".join(f'"{c}"' for c in NEW_COLUMNS) + "]].\n"
        "3) The new jobs are the Matches rows whose Apply URL is not in the sheet. If there are none, answer \"Tracker: "
        "no new jobs – https://docs.google.com/spreadsheets/d/<id>\" and stop.\n"
        "4) ONE update_cells on the first sheet for ALL k new jobs, range A<N+1>:M<N+k>, one row each: today's date "
        "(YYYY-MM-DD), Company, Role, Location, Type, Pay, Score, Deadline, Apply URL, \"New\", Found via, Contact, "
        "Contact link – copied from the table, never changed.\n"
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
        "Your input is the PROFILE block and the approved report (the savers run beside you). If the profile's "
        "WhatsApp line is none, answer \"WhatsApp: no number given – skipped.\" and stop. If you have no WhatsApp tools, "
        "answer \"WhatsApp is not connected – skipped.\" and stop. Otherwise call send_message once, recipient = the "
        "WhatsApp number (digits only, with country code), message = at most 9 lines: \"🎯 <k> job matches\" "
        "(k = rows in the report's Matches table), then its top 3 rows as \"<Score> · <Role> @ <Company> – <Apply "
        f"URL>\" (plus \" · <Contact>\" when it has one), then \"All <k> are going into your {TRACKER} sheet\", then "
        "\"Cover letters for the top <n> are being saved to your Gmail drafts\" when the report has cover letters. Then "
        "answer with ONLY \"WhatsApp: sent\", or the error."
    ),
    needs=[need(WHATSAPP, ["send_message"])],
    max_calls=2, timeout=60, runs_without_needs=True,
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
                {"name": "locations", "label": "Locations", "description": "e.g. Bangalore, Pune, Remote – empty = your resume's city, the cities near it and Remote"},
                {"name": "job_type", "label": "Internship or full-time", "description": "internship, full-time or both – empty = from your resume (internship for a fresher)"},
                {"name": "experience", "label": "Experience", "description": "e.g. fresher, 1 year – empty = from your resume"},
                {"name": "min_pay", "label": "Minimum stipend / salary", "description": "e.g. ₹10,000/month – empty = any"},
                {"name": "posted_within", "label": "Posted within (days)", "type": "number", "description": "e.g. 7 – empty = 14"},
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
        agent_node("c1", x(6), 300, **_llm(CONTACTS)),
        agent_node("w1", x(7), 300, **_llm(WRITER)),
        {"id": "ap", "type": "human_approval", "label": "Review the matches", "position": {"x": x(8), "y": 300},
         "approval_message": "Review the matches and cover letters before they're added to your tracker sheet, saved as "
                             "Gmail drafts and sent to your WhatsApp."},
        # Approved just above, so the saves themselves don't ask again.
        # Side by side: nothing here waits for another.
        agent_node("s1", x(9), 120, **_llm(TRACKER_SAVER)),
        agent_node("s2", x(9), 300, **_llm(DRAFT_SAVER)),
        agent_node("wa", x(9), 480, **_llm(NOTIFIER)),
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
        ("b1", "c1"), ("m1", "c1"),
        # The writer puts each match next to its contact.
        ("b1", "w1"), ("m1", "w1"), ("c1", "w1"),
        ("w1", "ap"),
        ("ap", "s1"), ("ap", "s2"), ("ap", "wa"), ("b1", "wa"),
        # The output gets the report (through the approval) and what each save did.
        ("ap", "out"), ("s1", "out"), ("s2", "out"), ("wa", "out"),
    ]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(lines)]
    return {
        "name": "Internship & job finder",
        "description": (
            "Attach your resume (📎) and run it – every field is optional and is read from the resume when empty (or "
            "add the resume to the workflow's knowledge base for a daily schedule). Searches job boards, LinkedIn, "
            "Internshala, Unstop and Wellfound live – for your resume's roles, skills and experience, in its city first, then the cities near it and remote, posted in the last 14 days – "
            "drops duplicates, old posts and scams, scores every job against your profile with the post's own words, "
            "finds recruiters and published hiring emails for the best ones, writes cover letters to them and – after "
            f"you approve – adds every match to a Google Sheet called \"{TRACKER}\", saves the letters as Gmail drafts "
            "and sends you a WhatsApp summary. Schedule it daily for fresh matches every morning."
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
