"""The job finder's code steps (``builder.workflows.code_steps``): what needs no AI, done in code – fast, the same
every time, and it never drops or miscopies a row the way a model does with a long table.

* ``job_filter``  the search lanes' JSON lines -> one list: duplicates merged; old / closed / fee-asking / wrong
                  level / too much experience / outside the wanted places / not-a-job-page links / already tracked
                  jobs dropped; the 100 most relevant kept, split into one batch per Matcher (``routed``) and the whole
                  list for Rank.
* ``job_rank``    the Matchers' skill lists -> a score worked out here (skills the post really names, experience,
                  place, pay, freshness), every job scoring 50+, near you first, the top ``Target`` kept as matches.
* ``job_report``  ranked jobs + checked contacts + the writer's skill gaps and letters -> the report the savers read.
                  It opens with the top TOP_SHOWN (10): the new matches, then tracker jobs from earlier runs that are
                  still open (not marked Applied / Not interested, passing today's checks), then lower matches.
                  The letters' To / Subject / greeting are filled in here, from a contact that passed the checks.

Texts between steps are JSON (one object per line from the AI steps, one document from these), so nothing is parsed
out of markdown tables.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from builder.workflows.code_steps import CodeInput, CodeResult, register

NOTE = "▸ "
TRACKER = "Internship Tracker"
TRACKER_COLUMNS = ("Date found", "Company", "Role", "Location", "Type", "Pay", "Score", "Deadline", "Apply URL", "Status",
                   "Found via", "Contact", "Contact link")
# What the Matchers read at most – more only makes the report slower, not better.
MAX_SCORED = 100
DEFAULT_TARGET = 25
MIN_SCORE = 50
# Every report opens with this many jobs: the new matches, then jobs from earlier runs still open, then lower matches.
TOP_SHOWN = 10
# A lower match (shown only to fill the top list): at least this much.
LOW_SCORE = 35
# A job from the tracker is shown again for this many days after it was found…
EARLIER_DAYS = 30
# …unless its Status (set by the person in the sheet) says they're done with it.
DONE_STATUSES = ("applied", "not interested", "rejected", "closed", "skip", "expired", "done", "withdrawn", "no ")
# A cover letter is written (and saved as a draft) only for a match scoring this much.
LETTER_MIN_SCORE = 70
# The most a job whose requirements weren't readable can score.
NOT_CHECKED_MAX = 55
FEE_WORDS = ("registration fee", "security deposit", "training fee", "kit fee", "joining fee", "refundable deposit",
             "pay to apply", "processing fee")
_TRACKING = re.compile(r"^(utm_.*|ref|refid|trk|trackingid|src|source|from|position|pagenum|origin)$", re.I)
_SECTION = re.compile(r"^--- (.+?) ---$", re.M)
FIELDS = ("company", "role", "location", "work_type", "job_type", "pay", "posted", "deadline", "url", "experience",
          "requirements", "source")
_ALIASES = {"title": "role", "job_title": "role", "apply_url": "url", "link": "url", "job_url": "url",
            "found_via": "source", "salary": "pay", "date_posted": "posted", "experience_range": "experience",
            "years": "experience"}
# Titles below a junior or mid candidate's level (a fresher still sees them).
BELOW_LEVEL = ("fresher", "freshers", "trainee", "graduate engineer trainee", "entry level", "entry-level")
_REMOTE = ("remote", "work from home", "wfh", "anywhere")
# Words job boards list as "skills" that name no skill (Naukri splits "Natural Language Processing" into these).
_NOT_A_SKILL = {"languages", "language", "machine", "vision", "intelligence", "processing", "data", "development",
                "program", "programming", "application", "applications", "fundamentals", "algorithms", "engineering",
                "software", "large", "microsoft", "solutions", "ai solutions", "analytics", "cloud", "automation",
                "it", "technology", "design", "management", "communication", "skills", "web", "computer", "science"}
# Spellings job sites mix up for the same city.
_SAME_PLACE = [{"gurgaon", "gurugram"}, {"bangalore", "bengaluru"}, {"bombay", "mumbai"}, {"delhi ncr", "ncr"},
               {"new delhi", "delhi"}, {"calcutta", "kolkata"}, {"madras", "chennai"}, {"poona", "pune"}]
_COUNTRY_WORDS = {"india", "in", "ind", "usa", "us", "uk", "remote", "hybrid", "on-site", "onsite", "on", "site"}
# A hiring address names hiring; anything else (ir@, press@, info@, support@) isn't one to apply to.
_HIRING_MAIL = re.compile(r"career|job|recruit|talent|hiring|hr\b|^hr|people|resume|^cv|apply|^ta\b|^ta[._-]", re.I)
_NOT_FOR_YOU_MAIL = re.compile(r"universit|campus|alumni|london|\buk\b|usa|\bus\b|nyc|newyork|boston|chicago|europe|"
                               r"emea|apac|singapore|dubai|uae|germany|canada|australia|sydney|paris|tokyo|japan",
                               re.I)


# ── Reading the steps' texts ─────────────────────────────────────────────────


def sections(parts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Each source's text; a join's "--- <step> ---" sections count as sources of their own."""
    out = []
    for label, text in parts:
        found = list(_SECTION.finditer(text or ""))
        if not found:
            out.append((label, text or ""))
            continue
        for i, m in enumerate(found):
            end = found[i + 1].start() if i + 1 < len(found) else len(text)
            out.append((m.group(1).strip(), text[m.end():end].strip()))
    return out


def json_objects(text: str) -> list[dict]:
    """Every JSON object in the text: one per line, or a JSON array (fenced or not)."""
    out: list[dict] = []
    cleaned = re.sub(r"^\s*```[\w-]*\s*$", "", text or "", flags=re.M).strip()
    if cleaned.startswith("["):
        try:
            data = json.loads(cleaned)
            return [d for d in data if isinstance(d, dict)]
        except ValueError:
            pass
    for line in cleaned.splitlines():
        line = line.strip().lstrip("-* ").rstrip(",")
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def parse_profile(text: str) -> dict[str, str]:
    """The Profile Builder's "Key: value" lines, keys lower-case ("skip titles", "posted within", …)."""
    out: dict[str, str] = {}
    block = text[text.find("PROFILE"):] if "PROFILE" in text else text
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and len(key) < 30 and not key.strip().startswith(("http", "{", "▸")):
            out.setdefault(key.strip().lower(), value.strip())
    return out


def profile_block(text: str) -> str:
    """The PROFILE lines alone (no tips, no notes) – what the Matchers are given."""
    if "PROFILE" not in text:
        return text.strip()
    lines = text[text.find("PROFILE"):].splitlines()
    return "\n".join(ln for ln in lines if ln.strip() and not ln.startswith(NOTE.strip())).strip()


def input_fields(parts: list[tuple[str, str]]) -> dict[str, str]:
    """The run's input fields as the input step writes them ("Inputs:" then "- name: value" lines)."""
    out: dict[str, str] = {}
    for _, text in parts:
        if "Inputs:" not in (text or ""):
            continue
        for m in re.finditer(r"^- ([a-z_]+): (.*)$", text[text.find("Inputs:"):], re.M):
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def _phone(value: str, profile: dict[str, str]) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10 and "india" in (profile.get("home") or "india").lower():
        digits = "91" + digits
    return digits if 11 <= len(digits) <= 15 else ""


def whatsapp_number(fields: dict[str, str], profile: dict[str, str]) -> str:
    """Digits with the country code from the WhatsApp field – the number the person chose."""
    return _phone(fields.get("whatsapp") or "", profile)


def resume_number(profile: dict[str, str]) -> str:
    """The resume's mobile number – only ever SUGGESTED (the send asks first, and the number can be changed there)."""
    return _phone(profile.get("phone") or "", profile)


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in re.split(r"[,;]", value or "") if v.strip() and v.strip().lower() not in ("none", "any", "empty")]


def _int(value, default: int) -> int:
    m = re.search(r"\d+", str(value or ""))
    return int(m.group()) if m else default


def _date(value) -> date | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def norm_url(url: str) -> str:
    url = (url or "").strip().strip("<>")
    if not url.lower().startswith("http"):
        return ""
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/"), query, ""))


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_COMPANY_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|llc|inc|corp|corporation|co|company|india|in|services?|solutions|technologies|"
    r"technology|tech|software|systems|group|global|international|consulting)\b\.?|\.(com|io|ai|in|co)\b", re.I)


def company_key(name: str) -> str:
    """One company however job boards write it: "Genpact India Pvt. Ltd." = "Genpact", "EaseMyTrip.com" = "Easemytrip",
    "EXL Service" = "EXL"."""
    key = _key(_COMPANY_SUFFIX.sub(" ", name or ""))
    return key or _key(name)


def _job_type(value: str) -> str:
    v = (value or "").lower()
    if "intern" in v:
        return "internship"
    if v.replace("-", "").replace("_", "").replace(" ", "") in ("fulltime", "permanent", "regular"):
        return "full-time"
    return value.strip()


def _job(raw: dict, lane: str) -> dict:
    job = {f: "" for f in FIELDS}
    for k, v in raw.items():
        k = _ALIASES.get(str(k).lower(), str(k).lower())
        if k in job and v not in (None, [], {}) and not job[k]:
            job[k] = (", ".join(map(str, v)) if isinstance(v, list) else str(v)).strip()
    job["source"] = job["source"] or lane
    job["job_type"] = _job_type(job["job_type"])
    return job


def _cell(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "/").strip()


# ── Checks on one job ────────────────────────────────────────────────────────


def is_job_page(url: str) -> bool:
    """The post itself, not a company page, a search or a list of jobs – job boards link all of these."""
    parts = urlsplit(url)
    host, path = parts.netloc.lower().removeprefix("www."), parts.path.lower()
    if "glassdoor." in host:
        return "/job-listing/" in path or "joblisting" in path
    if "naukri.com" in host:
        return "job-listings-" in path
    if "indeed." in host:
        return "viewjob" in path or "/rc/clk" in path or "/pagead/" in path or path.startswith("/job/")
    if "linkedin.com" in host:
        return "/jobs/view/" in path or "currentjobid=" in parts.query.lower()
    if "internshala.com" in host:
        return "/detail/" in path
    if "unstop.com" in host:
        return bool(re.search(r"/(jobs|internships|o)/[^/]*-\d{5,}", path))
    if "cutshort.io" in host:
        return path.startswith("/job/")
    if "wellfound.com" in host or "angel.co" in host:
        return bool(re.search(r"/jobs/\d+", path))
    if "instahyre.com" in host:
        return "/job-" in path
    if "foundit.in" in host:
        return "/job/" in path
    return True


_YEAR_RULES = [
    # "4 to 9 years", "4-9 Yrs", "3 – 5 years"
    (re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:-|–|—|to)\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I), True),
    # "3+ years", "3+ yrs"
    (re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+\s*(?:years?|yrs?)", re.I), False),
    # "minimum 5 years", "at least 2 years"
    (re.compile(r"(?:minimum|min\.?|at least|atleast)\s*(?:of\s*)?(\d{1,2}(?:\.\d)?)\s*(?:years?|yrs?)", re.I), False),
    # "5 years of experience"
    (re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:years?|yrs?)\s*(?:of\s*)?(?:[\w-]+\s+){0,3}?(?:experience|exp\b)", re.I), False),
]
_URL_YEARS = re.compile(r"-(\d{1,2})-to-(\d{1,2})-years?-", re.I)


def years_asked(job: dict) -> tuple[float, float | None] | None:
    """The post's (minimum, maximum) years of experience, from its own words or its Naukri link."""
    m = _URL_YEARS.search(job.get("url") or "")
    if m:
        return float(m.group(1)), float(m.group(2))
    text = f"{job.get('experience', '')} ; {job.get('role', '')} ; {job.get('requirements', '')}"
    for rule, ranged in _YEAR_RULES:
        for m in rule.finditer(text):
            low = float(m.group(1))
            high = float(m.group(2)) if ranged else None
            if low <= 25 and (high is None or low <= high <= 40):
                return low, high
    if re.search(r"\bfreshers?\b", text, re.I):
        return 0.0, 1.0
    return None


def candidate_years(profile: dict) -> float:
    text = (profile.get("experience") or "").lower()
    if not text or "fresher" in text:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(year|yr|month|mo)?", text)
    if not m:
        return 0.0
    value = float(m.group(1))
    return value / 12 if (m.group(2) or "").startswith("mo") else value


_PAY_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|l\b|k\b|cr\b|crores?)?")


def _amount(n: float, unit: str) -> float:
    if unit.startswith(("lakh", "lac", "lpa")) or unit == "l":
        return n * 1e5
    if unit == "k":
        return n * 1e3
    return n * 1e7 if unit.startswith("cr") else n


def yearly_pay(text: str) -> tuple[float, float] | None:
    """A stipend or salary as written ("₹30,000-40,000/month", "10-20 Lacs P.A.", "₹8L - ₹22L / yr") -> (low, high)
    a year, in the post's currency units."""
    t = (text or "").lower().replace(",", "")
    found = [(float(n), u or "") for n, u in _PAY_NUMBER.findall(t)]
    # "10-20 Lacs": the unit written once is the unit of both.
    unit = next((u for _, u in found if u), "")
    values = [v for v in (_amount(n, u or (unit if n < 1000 else "")) for n, u in found) if v >= 1000]
    if not values:
        return None
    per_month = bool(re.search(r"month|/mo\b|per mo|p\.?m\.?\b", t))
    low, high = min(values), max(values)
    return (low * 12, high * 12) if per_month else (low, high)


def _places(value: str) -> set[str]:
    out = set()
    for p in _csv(value):
        p = p.lower()
        out.add(p)
        for same in _SAME_PLACE:
            if p in same:
                out |= same
    return out


def place_group(job: dict, profile: dict) -> int | None:
    """0 near you (Home, Nearby, Region), 1 remote, 2 another place you asked for, 3 unclear (only a country or state
    given) – None when the post is in a city you didn't ask for."""
    where = f"{job.get('location', '')} {job.get('work_type', '')}".lower()
    near = _places(", ".join(_csv(profile.get("home"))[:1] + _csv(profile.get("nearby")) + _csv(profile.get("region"))))
    near -= _COUNTRY_WORDS
    if any(re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", where) for p in near):
        return 0
    if any(w in where for w in _REMOTE):
        return 1
    wanted = _places(profile.get("locations")) - near - _COUNTRY_WORDS
    if any(re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", where) for p in wanted):
        return 2
    # Only a country, a state code ("UP, IN") or nothing: can't tell – keep it, low.
    words = [w for w in re.split(r"[^a-z]+", job.get("location", "").lower()) if w and w not in _COUNTRY_WORDS]
    if not words or all(len(w) <= 2 for w in words):
        return 3
    asked = (profile.get("locations") or "").lower()
    return 3 if (not asked.strip() or "any" in re.split(r"[^a-z]+", asked)) else None


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", text.lower()))


def hiring_email(email: str, company: str) -> bool:
    """A published hiring address of THIS company, for the candidate's region: careers@acme.com yes; ir@, info@,
    a personal address, another company's domain or "UniversityHiring.London@" no."""
    m = re.fullmatch(r"([^@\s]+)@([a-z0-9.-]+\.[a-z]{2,})", (email or "").strip().lower())
    if not m:
        return False
    local, domain = m.groups()
    if domain in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"):
        return False
    words = [w for w in re.split(r"[^a-z0-9]+", company.lower()) if len(w) >= 3 and w not in (
        "pvt", "ltd", "private", "limited", "inc", "llc", "the", "and", "company", "technologies", "technology",
        "services", "solutions", "software", "india", "systems", "group", "international")]
    labels = domain.split(".")[:-1]
    if words and not any(w in _key("".join(labels)) for w in words) and not any(
            len(x) >= 3 and x not in ("co", "com", "careers", "jobs", "mail") and x in _key(company) for x in labels):
        return False
    return bool(_HIRING_MAIL.search(local)) and not _NOT_FOR_YOU_MAIL.search(local)


# ── Steps ────────────────────────────────────────────────────────────────────


def _not_for_you(job: dict, profile: dict, years: float) -> bool:
    """The checks every job gets that a tracker row can still go through: a real job page, a title at the level,
    not asking much more experience, a place asked for."""
    want = (profile.get("type") or "").lower()
    seniority = (profile.get("seniority") or "").lower()
    asked = years_asked(job)
    return (not is_job_page(norm_url(job["url"]))
            or any(_has_word(job["role"], w) for w in _csv(profile.get("skip titles")))
            or (seniority in ("junior", "mid") and want.startswith("full")
                and any(_has_word(job["role"], w) for w in BELOW_LEVEL))
            or bool(asked and asked[0] > years + 1)
            or place_group(job, profile) is None)


def earlier_jobs(rows: list[dict], profile: dict, today: date | None = None) -> list[dict]:
    """Tracker rows (from Seen Jobs) still worth showing: found in the last EARLIER_DAYS days, deadline not passed,
    the person hasn't marked them done (Applied, Not interested…), and they pass today's checks – a row an older
    version of this workflow let through doesn't come back. Best score first."""
    today = today or date.today()
    years, out, seen = candidate_years(profile), [], set()
    for r in rows:
        url, status = str(r.get("Apply URL") or ""), str(r.get("Status") or "").strip().lower()
        found, deadline = _date(r.get("Date found")), _date(r.get("Deadline"))
        # The same role at one company found on two sites is one job (company_key: "EaseMyTrip.com" = "Easemytrip").
        name = company_key(str(r.get("Company") or "")) + "|" + _key(str(r.get("Role") or ""))
        if (not url.startswith("http") or norm_url(url) in seen or name in seen
                or (status + " ").startswith(DONE_STATUSES)):
            continue
        if (found and (today - found).days > EARLIER_DAYS) or (deadline and deadline < today):
            continue
        job = {"company": str(r.get("Company") or ""), "role": str(r.get("Role") or ""),
               "location": str(r.get("Location") or ""), "work_type": "", "job_type": _job_type(str(r.get("Type") or "")),
               "pay": str(r.get("Pay") or ""), "posted": "", "deadline": str(r.get("Deadline") or ""), "url": url,
               "experience": "", "requirements": "", "source": str(r.get("Found via") or ""),
               "contact": str(r.get("Contact") or ""), "contact_link": str(r.get("Contact link") or ""),
               "score": _int(r.get("Score"), 0), "first_seen": found.isoformat() if found else "",
               "status": str(r.get("Status") or "")}
        if _not_for_you(job, profile, years):
            continue
        seen |= {norm_url(url), name}
        out.append(job)
    return sorted(out, key=lambda j: -j["score"])


@register("job_filter")
def job_filter(inp: CodeInput) -> CodeResult:
    profile_text = next((t for _, t in inp.parts if "PROFILE" in t), "")
    profile = parse_profile(profile_text)
    today = date.today()
    cutoff = today - timedelta(days=_int(profile.get("posted within"), 14))
    want = (profile.get("type") or "").lower()
    seniority = (profile.get("seniority") or "").lower()
    skip_titles = _csv(profile.get("skip titles"))
    excludes = [e.lower() for e in _csv(profile.get("exclude")) if "fee" not in e.lower() and "unpaid" not in e.lower()]
    unpaid_out = "unpaid" in (profile.get("exclude") or "").lower()
    years = candidate_years(profile)
    min_pay = yearly_pay(profile.get("min pay") or "")

    seen: set[str] = set()
    tracked: list[dict] = []
    per_lane: dict[str, int] = {}
    found: list[dict] = []
    for label, text in sections([p for p in inp.parts if "PROFILE" not in p[1] and "Inputs:" not in p[1]]):
        if text.lstrip().startswith("SEEN"):
            seen |= {norm_url(u.rstrip('",')) for u in re.findall(r"https?://[^\s\"]+", text)}
            tracked += [o for o in json_objects(text) if o.get("Apply URL")]
            continue
        jobs = [_job(o, label) for o in json_objects(text)]
        per_lane[label] = len(jobs)
        found += jobs

    counts = {"found": len(found), "duplicates": 0, "in_tracker": 0, "old_or_closed": 0, "fee_or_unpaid": 0,
              "title_type_or_excluded": 0, "too_much_experience": 0, "outside_places": 0, "pay_below_min": 0,
              "not_a_job_page": 0, "no_link": 0, "kept": 0, "not_scored": 0}
    by_url: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for job in found:
        url = norm_url(job["url"])
        if not url:
            counts["no_link"] += 1
            continue
        if not is_job_page(url):
            counts["not_a_job_page"] += 1
            continue
        if url in seen:
            counts["in_tracker"] += 1
            continue
        # The same role at the same company is one job, whichever cities it is posted for.
        name = company_key(job["company"]) + "|" + _key(job["role"])
        twin = by_url.get(url) or (by_name.get(name) if _key(job["company"]) else None)
        if twin is not None:
            counts["duplicates"] += 1
            if job["location"] and _key(job["location"]) not in _key(twin["location"]):
                twin["location"] = f"{twin['location']} / {job['location']}" if twin["location"] else job["location"]
            for f in FIELDS:
                if not twin[f] and job[f]:
                    twin[f] = job[f]
            if job["source"] and job["source"] not in twin["source"]:
                twin["source"] += f", {job['source']}"
            continue
        job["url_key"] = url
        by_url[url] = job
        by_name[name] = job

    kept: list[dict] = []
    for job in by_url.values():
        posted, deadline = _date(job["posted"]), _date(job["deadline"])
        text = f"{job['role']} {job['requirements']} {job['pay']}".lower()
        asked = years_asked(job)
        pay = yearly_pay(job["pay"])
        group = place_group(job, profile)
        if (posted and posted < cutoff) or (deadline and deadline < today):
            counts["old_or_closed"] += 1
        elif any(w in text for w in FEE_WORDS) or (unpaid_out and "unpaid" in text):
            counts["fee_or_unpaid"] += 1
        elif (any(_has_word(job["role"], w) for w in skip_titles)
              or (seniority in ("junior", "mid") and want.startswith("full")
                  and any(_has_word(job["role"], w) for w in BELOW_LEVEL))
              or ("intern" in job["job_type"].lower() and want.startswith("full"))
              or ("full" in job["job_type"].lower() and want.startswith("intern"))
              or any(e in f"{job['company']} {job['role']}".lower() for e in excludes)):
            counts["title_type_or_excluded"] += 1
        elif asked and asked[0] > years + 1:
            counts["too_much_experience"] += 1
        elif group is None:
            counts["outside_places"] += 1
        elif min_pay and pay and pay[1] < min_pay[0]:
            counts["pay_below_min"] += 1
        else:
            if asked:
                job["years"] = f"{asked[0]:g}" + (f"-{asked[1]:g}" if asked[1] is not None else "+")
            kept.append(job)

    # The most relevant first: skill and role words the post shares with the profile.
    words = {w for w in re.findall(r"[a-z][a-z0-9+#.]{1,}", " ".join(
        [profile.get("skills", ""), profile.get("roles", ""), profile.get("search phrases", "")]).lower()) if len(w) > 2}
    for job in kept:
        job["relevance"] = len(words & set(re.findall(r"[a-z][a-z0-9+#.]{1,}", f"{job['role']} {job['requirements']}".lower())))
    kept.sort(key=lambda j: -j["relevance"])
    counts["not_scored"] = max(0, len(kept) - MAX_SCORED)
    kept = kept[:MAX_SCORED]
    counts["kept"] = len(kept)
    for i, job in enumerate(kept, 1):
        job["id"] = f"J{i}"

    matchers = [t for t, kind in inp.targets if kind == "agent"]
    routed: dict[str, str] = {}
    block = profile_block(profile_text)
    for i, target in enumerate(matchers):
        batch = kept[i::len(matchers)]
        if not batch:
            routed[target] = "NO JOBS"
            continue
        lines = "\n".join(json.dumps({k: j.get(k, "") for k in ("id", "company", "role", "job_type", "years",
                                                                 "requirements")},
                                     ensure_ascii=False) for j in batch)
        routed[target] = f"{block}\n\nJOBS – {len(batch)}, one JSON object per line:\n{lines}"
    payload = json.dumps({"profile": profile, "jobs": kept, "counts": counts, "lanes": per_lane,
                          "earlier": earlier_jobs(tracked, profile, today)}, ensure_ascii=False)
    for target, kind in inp.targets:
        if kind != "agent":
            routed[target] = payload

    lanes = " · ".join(f"{k} {v}" for k, v in per_lane.items()) or "no search answered"
    dropped = counts["found"] - counts["kept"] - counts["duplicates"] - counts["not_scored"]
    output = (
        f"Found {counts['found']} jobs ({lanes}).\n"
        f"Kept {counts['kept']} to score: {counts['duplicates']} duplicates merged, {counts['in_tracker']} already in "
        f"your tracker, {counts['old_or_closed']} old or closed, {counts['fee_or_unpaid']} asking a fee or unpaid, "
        f"{counts['title_type_or_excluded']} wrong level, type or excluded, {counts['too_much_experience']} asking "
        f"more experience than you have, {counts['outside_places']} in cities you didn't ask for, "
        f"{counts['pay_below_min']} paying below your minimum, {counts['not_a_job_page']} links that aren't a job post, "
        f"{counts['no_link']} without a link"
        + (f", {counts['not_scored']} least relevant left out" if counts["not_scored"] else "") + ".\n"
        f"{NOTE}Checked {counts['found']} jobs: {counts['kept']} new to score, {max(dropped, 0)} dropped, "
        f"{counts['duplicates']} duplicates"
    )
    return CodeResult(output=output, routed=routed)


def _group(job: dict, profile: dict) -> int:
    """Which section a job goes in: 0 near you, 1 remote, 2 other places (another wanted city or unclear)."""
    g = place_group(job, profile)
    return 2 if g is None else min(g, 2)


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(c for c, _ in columns) + " |\n|" + "---|" * len(columns)
    return head + "".join("\n| " + " | ".join(_cell(r.get(k)) for _, k in columns) + " |" for r in rows)


def _list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r"[,;]", str(value or "")) if v.strip() and v.strip().lower() not in ("none", "empty")]


def score_job(job: dict, match: dict, profile: dict, today: date | None = None) -> tuple[int, str, str]:
    """The score out of 100, worked out here from facts – the Matcher only says which of the post's skills the
    candidate has. Skills 40 (only skills the post really names count), experience 25, place 15, pay 10, fresh 10.
    -> (score, why, missing)."""
    today = today or date.today()
    post = _key(f"{job.get('role', '')} {job.get('requirements', '')} {job.get('experience', '')}")
    real = lambda s: _key(s) and s.strip().lower() not in _NOT_A_SKILL  # noqa: E731
    matched = [s for s in _list(match.get("matched")) if real(s) and _key(s) in post]
    missing = [s for s in _list(match.get("missing")) if real(s)]
    if not (job.get("requirements") or "").strip():
        skills, skill_note = 10, "requirements not listed – check the post"
    elif not matched and not missing:
        skills, skill_note = 15, ""
    else:
        skills, skill_note = round(40 * len(matched) / (len(matched) + len(missing))), ""

    years, asked = candidate_years(profile), years_asked(job)
    if asked is None:
        eligibility, years_note = 18, ""
    else:
        low, high = asked
        span = f"{low:g}-{high:g}" if high is not None else f"{low:g}+"
        years_note = f"asks {span} yrs (you {years:g})"
        if low <= years:
            eligibility = 12 if (high is not None and years > high + 2) else 25
        elif low <= years + 1:
            eligibility = 12
        else:
            eligibility = 0

    group = place_group(job, profile)
    place = {0: 15, 1: 10, 2: 8, 3: 3}.get(group, 0)
    if group == 0 and not any(p.lower() in job.get("location", "").lower() for p in _csv(profile.get("home"))[:1]):
        place = 13

    pay, min_pay = yearly_pay(job.get("pay") or ""), yearly_pay(profile.get("min pay") or "")
    if pay is None:
        pay_points = 5
    elif min_pay:
        pay_points = 10 if pay[1] >= min_pay[0] else 0
    else:
        # No minimum given: a stipend-level salary for someone with work experience still counts against it.
        pay_points = 0 if (years >= 1 and pay[1] < 300_000) else 10

    posted = _date(job.get("posted"))
    fresh = 4 if posted is None else 10 if (today - posted).days <= 7 else 5

    score = skills + eligibility + place + pay_points + fresh
    # A post whose requirements we never saw can't be shown to fit: below every job that was checked.
    if skill_note:
        score = min(score, NOT_CHECKED_MAX)
    ruled = str(match.get("ruled_out") or "").strip()
    if ruled.lower() in ("no", "none", "false", "null", "n/a"):
        ruled = ""
    if ruled:
        score = 0
    why = " · ".join(x for x in (
        ("Matched: " + ", ".join(matched[:6])) if matched else "", skill_note, years_note,
        _short_places(job.get("location", ""), profile) if group in (0, 2) else "remote" if group == 1 else "",
    ) if x)
    if ruled:
        why = f"Ruled out: {ruled}"
    return score, why, ", ".join(missing[:6])


def _short_places(location: str, profile: dict) -> str:
    """"Hyderabad / Noida / Mumbai / …" (one post merged from many cities) -> the nearest three first, "+5 more"."""
    places = [p.strip() for p in location.split(" / ") if p.strip()]
    if len(places) <= 3:
        return location
    places.sort(key=lambda p: {None: 9}.get(g := place_group({"location": p, "work_type": ""}, profile), g))
    return " / ".join(places[:3]) + f" +{len(places) - 3} more"


@register("job_rank")
def job_rank(inp: CodeInput) -> CodeResult:
    data: dict = {}
    scores: dict[str, dict] = {}
    for _, text in sections(inp.parts):
        stripped = text.strip()
        if stripped.startswith("{") and '"jobs"' in stripped:
            try:
                data = json.loads(stripped)
                continue
            except ValueError:
                pass
        for obj in json_objects(text):
            if obj.get("id"):
                scores[str(obj["id"]).strip()] = obj
    profile, jobs = data.get("profile") or {}, data.get("jobs") or []
    target = _int(profile.get("target"), DEFAULT_TARGET)

    matched, low = [], []
    for job in jobs:
        s = scores.get(job["id"])
        if s is None:
            continue
        score, why, missing = score_job(job, s, profile)
        row = {**job, "score": score, "why": why, "missing": missing, "location": _short_places(job["location"], profile)}
        if score >= MIN_SCORE:
            matched.append(row)
        elif score >= LOW_SCORE:
            low.append(row)
    low.sort(key=lambda j: -j["score"])
    matched.sort(key=lambda j: (_group(j, profile), -j["score"]))
    # The best Target overall (whatever the place), shown nearest first.
    best = sorted(matched, key=lambda j: -j["score"])[:target]
    keep = {j["id"] for j in best}
    top = [j for j in matched if j["id"] in keep]
    extra = [j for j in matched if j["id"] not in keep]
    counts = {**(data.get("counts") or {}), "scored": len(scores), "matched": len(matched)}

    columns = [("Score", "score"), ("Company", "company"), ("Role", "role"), ("Location", "location"),
               ("Type", "job_type"), ("Pay", "pay"), ("Apply URL", "url"), ("Why it fits", "why"),
               ("Missing skills", "missing")]
    table = _table(top, columns) if top else "No job scored 50 or more."
    routed = {}
    for t, kind in inp.targets:
        routed[t] = (json.dumps({"profile": profile, "top": top, "extra": extra, "counts": counts,
                                 "lanes": data.get("lanes") or {}, "low": low[:TOP_SHOWN],
                                 "earlier": data.get("earlier") or []}, ensure_ascii=False)
                     if kind == "code" else f"TOP MATCHES (best first)\n{table}")
    top_one = max(top, key=lambda j: j["score"]) if top else None
    best_line = f"best: {top_one['score']} · {top_one['role']} @ {top_one['company']}" if top_one else "none scored 50+"
    output = (f"{table}\n\n{len(extra)} more scored 50+ (they go to the tracker as Extra).\n"
              f"{NOTE}{len(matched)} matches scored 50+ – top {len(top)} in the report, {best_line}")
    return CodeResult(output=output, routed=routed)


_LETTER = re.compile(r"^### (.+?)\s*$", re.M)


def _letters(writer: str) -> tuple[str, list[tuple[str, str]]]:
    """The writer's text -> (everything before the cover letters, [(heading, body)])."""
    at = writer.find("## Cover letters")
    if at < 0:
        return writer, []
    head, rest = writer[:at], writer[at + len("## Cover letters"):]
    found = list(_LETTER.finditer(rest))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(rest)
        out.append((m.group(1).strip(), rest[m.end():end].strip()))
    if not found and rest.strip():
        head += "## Cover letters\n" + rest.strip()
    return head.rstrip(), out


def _letter_job(heading: str, jobs: list[dict]) -> dict | None:
    company = _key(heading.split("–")[0].split(" - ")[0])
    hits = [j for j in jobs if _key(j["company"]) and (_key(j["company"]) in company or company in _key(j["company"]))]
    if len(hits) > 1:
        role = _key(heading)
        hits = [j for j in hits if _key(j["role"]) in role] or hits
    return hits[0] if hits else None


def _fill_letter(heading: str, body: str, job: dict | None, contact: dict | None, profile: dict) -> tuple[str, dict]:
    """To / Subject from facts, the greeting by name when a real person was found, and a warning on any skill the
    letter claims that the post asks for but the profile lacks. -> (the letter in Markdown, the draft to save)."""
    body = re.sub(r"^(To|Subject):.*$\n?", "", body, flags=re.M).strip()
    tips = ""
    if "Resume tips:" in body:
        body, tips = body.split("Resume tips:", 1)
        body, tips = body.strip(), "Resume tips:" + tips.rstrip()
    name = (contact or {}).get("name") or ""
    if name and name.lower() not in ("none", "none found"):
        body = re.sub(r"^Dear [^,\n]*,", f"Dear {name.split()[0]},", body, count=1, flags=re.M)
    email = (contact or {}).get("email") or ""
    to = email if "@" in email else "none found – the draft goes to your own address; add the recruiter's before sending"
    role = job["role"] if job else heading.split("–", 1)[-1].strip()
    subject = f"Application for {role} – {profile.get('name') or 'me'}"
    warnings = []
    for skill in _list((job or {}).get("missing")):
        if len(_key(skill)) >= 3 and _key(skill) in _key(body):
            warnings.append(f"- ⚠ The letter mentions {skill}, which the post asks for but your resume doesn't show "
                            "– remove it or be ready to back it up.")
    if warnings:
        tips = (tips or "Resume tips:") + "\n" + "\n".join(warnings)
    markdown = "\n".join((f"### {heading}", f"To: {to}", f"Subject: {subject}", "", body, "", tips)).rstrip()
    return markdown, {"heading": heading, "to": email if "@" in email else "", "subject": subject, "body": body}


@register("job_report")
def job_report(inp: CodeInput) -> CodeResult:
    ranked: dict = {}
    contacts: dict[str, dict] = {}
    writer = ""
    fields = input_fields(inp.parts)
    for _, text in sections(inp.parts):
        stripped = text.strip()
        if "Inputs:" in stripped and not stripped.startswith(("{", "#")):
            continue
        if stripped.startswith("{") and '"top"' in stripped:
            try:
                ranked = json.loads(stripped)
                continue
            except ValueError:
                pass
        objs = [o for o in json_objects(text) if o.get("company")]
        if objs and not stripped.startswith("#"):
            for o in objs:
                name, email = str(o.get("name") or "").strip(), str(o.get("email") or "").strip()
                # Only an address that is really this company's hiring one.
                if email and not hiring_email(email, str(o["company"])):
                    email = ""
                if name.lower() in ("", "none", "none found") and not email:
                    continue
                key = _key(o["company"])
                # One per company: one with a published email first.
                if key not in contacts or ("@" in email and "@" not in contacts[key]["email"]):
                    contacts[key] = {"name": "" if name.lower() in ("none", "none found") else name,
                                     "title": str(o.get("title") or ""), "email": email,
                                     "link": str(o.get("link") or o.get("contact_link") or "")}
            continue
        if "## " in text:
            writer = "\n".join(ln for ln in text.splitlines() if not ln.startswith(NOTE.strip())).strip()

    top, extra = ranked.get("top") or [], ranked.get("extra") or []
    counts, lanes, profile = ranked.get("counts") or {}, ranked.get("lanes") or {}, ranked.get("profile") or {}
    every = top + extra
    for job in every:
        c = contacts.get(_key(job["company"]))
        if c:
            job["contact"] = (f"{c['name']} ({c['title']})" if c["name"] and c["title"] else c["name"] or c["email"])
            job["contact_link"] = c["link"] or c["email"]

    groups = [_group(j, profile) for j in every]
    full_time = sum(1 for j in every if "intern" not in j["job_type"].lower())
    columns = [("Score", "score"), ("Company", "company"), ("Role", "role"), ("Location", "location"),
               ("Type", "job_type"), ("Pay", "pay"), ("Posted", "posted"), ("Deadline", "deadline"),
               ("Apply URL", "url"), ("Why it fits", "why"), ("Missing skills", "missing"), ("Found via", "source"),
               ("Contact", "contact"), ("Contact link", "contact_link")]

    def by_place(rows: list[dict]) -> list[str]:
        out = []
        for g, title in ((0, "Near you"), (1, "Remote"), (2, "Other places")):
            part = sorted([r for r in rows if _group(r, profile) == g], key=lambda r: -r["score"])
            if part:
                out += [f"### {title} ({len(part)})", _table(part, columns)]
        return out

    # The top list: the new matches, then jobs from earlier runs still open, then lower matches – always TOP_SHOWN
    # when there are that many, so a day with few new posts still shows what's worth applying to.
    new_urls = {norm_url(j["url"]) for j in every} | {company_key(j["company"]) + "|" + _key(j["role"]) for j in every}
    shown = [{**j, "kind": "🆕 New"} for j in sorted(every, key=lambda j: -j["score"])[:TOP_SHOWN]]
    for j in ranked.get("earlier") or []:
        if len(shown) >= TOP_SHOWN:
            break
        if norm_url(j["url"]) not in new_urls and company_key(j["company"]) + "|" + _key(j["role"]) not in new_urls:
            shown.append({**j, "kind": f"Found {j.get('first_seen') or 'earlier'}" + (
                f" · {j['status']}" if j.get("status") and j["status"] not in ("New", "Extra") else ""),
                "why": j.get("why") or "from an earlier run – still open"})
    low_shown = []
    for j in ranked.get("low") or []:
        if len(shown) >= TOP_SHOWN:
            break
        low_shown.append(j)
        shown.append({**j, "kind": "Lower match"})
    top_columns = [("Score", "score"), ("", "kind"), ("Company", "company"), ("Role", "role"), ("Location", "location"),
                   ("Pay", "pay"), ("Apply URL", "url"), ("Why it fits", "why"), ("Missing skills", "missing"),
                   ("Contact", "contact")]
    n_earlier = sum(1 for j in shown if j["kind"].startswith("Found"))

    number = whatsapp_number(fields, profile)
    suggested = "" if number else resume_number(profile)
    lane_line = " · ".join(f"{k} {v}" for k, v in lanes.items())
    parts = [
        f"# Job matches – {date.today().isoformat()}",
        f"{len(every)} new matches scored 50+: {full_time} full-time, {len(every) - full_time} internships · "
        f"{groups.count(0)} near you, {groups.count(1)} remote, {groups.count(2)} other places.",
        f"Searched: {lane_line or 'no source answered'}. {counts.get('found', 0)} found → {counts.get('kept', 0)} new "
        f"after removing duplicates, old posts, wrong levels, non-job links and jobs already in your tracker → "
        f"{counts.get('matched', 0)} scored 50+.",
        f"## Top {len(shown)}" if shown else "## Top jobs",
        (f"{min(len(every), TOP_SHOWN)} new, {n_earlier} from earlier runs (still open – mark one Applied or Not "
         f"interested in the sheet's Status and it stops coming back), {len(low_shown)} lower matches you could "
         "still apply to." if shown else "Nothing to show yet – no new match, and nothing open in your tracker."),
        *([_table(shown, top_columns)] if shown else []),
        "## All new matches",
        *(by_place(top) if top else ["No new job scored 50 or more today."]),
    ]
    if extra:
        parts += ["## More new matches", "Also scored 50+; they go into your tracker with Status \"Extra\".",
                  *by_place(extra)]
    filled: list[str] = []
    drafts: list[dict] = []
    if writer:
        head, letters = _letters(writer)
        parts.append(head)
        for heading, body in letters:
            job = _letter_job(heading, top) or _letter_job(heading, extra)
            # Letters only for the strong matches, whatever the writer did.
            if job is not None and job.get("score", 0) < LETTER_MIN_SCORE:
                continue
            markdown, draft = _fill_letter(heading, body, job, contacts.get(_key(job["company"])) if job else None, profile)
            filled.append(markdown)
            drafts.append(draft)
        if filled:
            parts.append("## Cover letters\n\n" + "\n\n".join(filled))
    if number:
        parts.append(f"WhatsApp to: {number}")
    elif suggested:
        parts.append(f"WhatsApp to: {suggested} – from your resume; you'll be asked before anything is sent, and can "
                     "change the number there (or fill in the WhatsApp field)")
    else:
        parts.append("WhatsApp to: none – no number in the WhatsApp field or your resume")
    top_one = max(top, key=lambda j: j["score"]) if top else None
    best = f" – best: {top_one['score']} · {top_one['role']} @ {top_one['company']}" if top_one else ""
    parts.append(f"{NOTE}{len(every)} matches{best}")
    # The savers that are code get the facts themselves – rows, drafts, the message – not a table to read back.
    message = "\n".join([f"🎯 Top {len(shown)} jobs today – {len(every)} new"] + [
        f"{j['score']} · {j['role']} @ {j['company']} – {j['url']}" + ("" if j["kind"].startswith("🆕") else " (seen before)")
        + (f" · {j['contact']}" if j.get("contact") else "")
        for j in shown[:3]] + ([f"All {len(every)} new ones are going into your {TRACKER} sheet"] if every else []) + (
        [f"Cover letters for the top {len(drafts)} are being saved to your Gmail drafts"] if drafts else []))
    payload = json.dumps({
        "date": date.today().isoformat(), "top": top, "extra": extra, "low": low_shown, "drafts": drafts,
        "name": profile.get("name") or "",
        "whatsapp": {"to": number or suggested, "from_resume": bool(suggested), "message": message if shown else ""},
        "ask": (fields.get("ask_before_saving") or "").strip().lower() in ("yes", "y", "true", "1", "ask", "haan", "ha"),
    }, ensure_ascii=False)
    return CodeResult(output="\n\n".join(parts), routed={t: payload for t, kind in inp.targets if kind == "code"})
