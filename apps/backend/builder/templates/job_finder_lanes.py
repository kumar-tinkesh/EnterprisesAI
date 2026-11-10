"""The job finder's search lanes that are plain API calls, made in code (``builder.workflows.code_steps``,
``tool_needs``): the searches are fixed by the PROFILE, and every job comes from the tool's own fields – the post's
real link, its years and skills, the whole description – instead of a model copying a long list (where it kept
company pages for job links and saw only the first part of each answer).

* ``lane_indeed`` / ``lane_naukri`` / ``lane_glassdoor``  JobSpy, one site (Glassdoor with Google Jobs) each: the
  first three Search phrases at Home (30 km reaches the Nearby cities) and the first one remote – side by side.
* ``lane_startups``  Startup Jobs: the first four phrases in the Home country.
* ``lane_linkedin``  LinkedIn, one call at a time (it answers a burst with HTTP 429): three searches, then the full
  post of the most promising jobs while the time lasts.

Each answers the lanes' JSON lines (``job_finder.JOB_RULES``) and a "▸ " line; a lane whose system isn't connected
or that fails answers with none, and the join goes on with the rest. The open-web lanes (Internshala, Unstop,
Wellfound, Cutshort) stay AI steps: their pages need reading.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta

from builder.templates.job_finder_steps import NOTE, _YEAR_RULES, _csv, _int, parse_profile, sections
from builder.runs.db import is_transient
from builder.workflows.code_steps import CodeInput, CodeResult, StepTools, register

JOBSPY, STARTUPS, LINKEDIN = "JobSpy", "Startup Jobs", "LinkedIn"
# How long a lane may search; what's found by then is answered.
LANE_SECONDS = 70
LINKEDIN_SECONDS = 60
# Posts LinkedIn is asked for in full (each ~3-5 s, one at a time) – the most promising few; LinkedIn is the slowest
# lane, and every lane waits for it.
LINKEDIN_DETAILS = 3
REQUIREMENTS_CHARS = 700
_HEADING = re.compile(
    r"(requirements?|qualifications?|skills?(?: required| & experience| and experience)?|what (?:you(?:'ll)?|we) "
    r"(?:need|bring|look for|are looking for)|must[- ]haves?|who you are|eligibility|key skills|technical skills|"
    r"your profile|about you)\s*[:\n]", re.I)


def _profile(inp: CodeInput) -> dict[str, str]:
    return parse_profile(next((t for _, t in inp.parts if "PROFILE" in t), ""))


def search_phrases(profile: dict) -> list[str]:
    raw = profile.get("search phrases") or ""
    phrases = [p.strip().strip('"') for p in re.split(r";" if ";" in raw else r",", raw) if p.strip()]
    return phrases or _csv(profile.get("roles"))


def _home(profile: dict) -> tuple[str, str, str]:
    """(Home as job boards take it "New Delhi, India", its city, its country)."""
    parts = _csv(profile.get("home"))
    city = parts[0] if parts else ""
    country = parts[-1] if len(parts) > 1 else "India"
    return ", ".join(parts) or country, city, country


def requirements_from(description: str) -> tuple[str, str]:
    """A post's description -> (its requirements part, at most REQUIREMENTS_CHARS; the years it asks, as written)."""
    text = re.sub(r"[*_`#>|]+", " ", description or "")
    text = re.sub(r"\\([-.()])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    years = ""
    for rule, _ in _YEAR_RULES:
        m = rule.search(text)
        if m:
            years = m.group(0)
            break
    m = _HEADING.search(text)
    start = m.start() if m else 0
    return text[start:start + REQUIREMENTS_CHARS], years


def _objects_after(text: str, key: str) -> list[dict]:
    """The objects of the list under ``key`` in a JSON text – all those that are complete, so an answer cut off at
    the size limit still gives every job before the cut."""
    at = text.find(f'"{key}"')
    if at < 0:
        return []
    i = text.find("[", at)
    decoder, out = json.JSONDecoder(), []
    while i >= 0:
        i = text.find("{", i + 1)
        if i < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            break
        if isinstance(obj, dict):
            out.append(obj)
        i = end
        nxt = text[end:end + 20].lstrip()
        if not nxt.startswith(","):
            break
    return out


def _money(n) -> str:
    n = float(n)
    return f"{round(n / 1e5, 1):g}L" if n >= 1e5 else f"{n:,.0f}"


def _pay(j: dict) -> str:
    low, high, cur, per = j.get("min_amount"), j.get("max_amount"), j.get("currency") or "", j.get("interval") or ""
    if not low and not high:
        return ""
    sign = "₹" if cur == "INR" else f"{cur} "
    span = f"{sign}{_money(low)} - {sign}{_money(high)}" if low and high and low != high else f"{sign}{_money(low or high)}"
    return f"{span} / {'month' if per.startswith('month') else 'yr' if per.startswith('year') else per}".rstrip(" /")


def jobspy_job(j: dict) -> dict:
    requirements, years = requirements_from(j.get("description") or "")
    skills = j.get("skills") or ""
    wfh = (j.get("work_from_home_type") or "").lower()
    return {
        "company": j.get("company") or "", "role": j.get("title") or "", "location": j.get("location") or "",
        "work_type": "remote" if j.get("is_remote") or "home" in wfh or "remote" in wfh else
                     "hybrid" if "hybrid" in wfh else "on-site" if wfh else "",
        "job_type": j.get("job_type") or "", "pay": _pay(j), "posted": j.get("date_posted") or "", "deadline": "",
        "url": j.get("job_url") or "", "experience": j.get("experience_range") or years,
        "requirements": "; ".join(x for x in (skills, requirements) if x)[:REQUIREMENTS_CHARS + 200],
        "source": f"JobSpy ({(j.get('site') or '').title()})",
    }


async def _within(seconds: float, calls: list) -> list:
    """Run the calls side by side; the ones not done after ``seconds`` are given up (None)."""
    tasks = [asyncio.ensure_future(c) for c in calls]
    done, pending = await asyncio.wait(tasks, timeout=seconds)
    for t in pending:
        t.cancel()
    for t in done:
        # A database hiccup isn't a slow source: the run resumes from its checkpoint instead of losing the lane.
        if t.exception() is not None and is_transient(t.exception()):
            raise t.exception()
    return [t.result() if t in done and not t.exception() else None for t in tasks]


def _answer(jobs: list[dict], where: str, failed: list[str]) -> CodeResult:
    lines = [json.dumps(j, ensure_ascii=False) for j in jobs]
    if failed:
        lines.append(f"Not answered: {'; '.join(failed)[:300]}")
    lines.append(f"{NOTE}{len(jobs)} jobs on {where}")
    return CodeResult(output="\n".join(lines))


async def _jobspy_lane(inp: CodeInput, sites: list[str], where: str, wanted: int) -> CodeResult:
    tools: StepTools | None = inp.tools
    if tools is None or not tools.has(JOBSPY, "search_jobs"):
        return _answer([], where, ["JobSpy is not connected"])
    profile = _profile(inp)
    phrases = search_phrases(profile)
    if not phrases:
        return _answer([], where, ["the profile has no search phrases"])
    home, city, country = _home(profile)
    days = _int(profile.get("posted within"), 14)
    internship = (profile.get("type") or "").lower().startswith("intern")
    base = {"site_name": sites, "results_wanted": wanted, "country_indeed": country.lower()}
    # Indeed can't take a job type and an age together; "full-time" as a job type is rejected – leave it out.
    base.update({"job_type": "internship"} if internship else {"hours_old": days * 24})
    searches = [{**base, "search_term": p, "location": home, "distance": 30} for p in phrases[:3]]
    searches.append({**base, "search_term": phrases[0], "location": country, "is_remote": True})
    if "google" in sites:
        for s in searches:
            s["google_search_term"] = f"{s['search_term']} jobs near {city or country} since {days} days"
    answers = await _within(LANE_SECONDS, [
        tools.call(JOBSPY, "search_jobs", s, key=f"{sites[0]}:{i}", timeout=LANE_SECONDS) for i, s in enumerate(searches)])
    jobs, failed = [], []
    for s, a in zip(searches, answers):
        if a is None or a.is_error:
            failed.append(f"{s['search_term']}: {'took too long' if a is None else a.text[:120]}")
            continue
        jobs += [jobspy_job(j) for j in _objects_after(a.text, "jobs")]
    return _answer(jobs, where, failed)


@register("lane_indeed")
async def lane_indeed(inp: CodeInput) -> CodeResult:
    # With whole descriptions 30 already fill the answer's size limit.
    return await _jobspy_lane(inp, ["indeed"], "Indeed", 30)


@register("lane_naukri")
async def lane_naukri(inp: CodeInput) -> CodeResult:
    return await _jobspy_lane(inp, ["naukri"], "Naukri", 50)


@register("lane_glassdoor")
async def lane_glassdoor(inp: CodeInput) -> CodeResult:
    return await _jobspy_lane(inp, ["glassdoor", "google"], "Glassdoor + Google Jobs", 50)


def startup_job(j: dict) -> dict:
    loc = j.get("location") or {}
    place = ", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x) if isinstance(loc, dict) else str(loc)
    salary = j.get("salary")
    pay = ""
    if isinstance(salary, dict) and (salary.get("min") or salary.get("max")):
        pay = f"{salary.get('currency', '')} {salary.get('min') or ''}-{salary.get('max') or ''} {salary.get('period', '')}".strip()
    roles = ", ".join(r.get("title", "") for r in j.get("roles") or [] if isinstance(r, dict))
    return {
        "company": (j.get("company") or {}).get("name", "") if isinstance(j.get("company"), dict) else str(j.get("company") or ""),
        "role": j.get("title") or "", "location": place, "work_type": j.get("workplace_type") or "",
        "job_type": j.get("employment_type") or "", "pay": pay, "posted": (j.get("published_at") or "")[:10],
        "deadline": "", "url": j.get("url") or "", "experience": "", "requirements": roles, "source": "Startup Jobs",
    }


@register("lane_startups")
async def lane_startups(inp: CodeInput) -> CodeResult:
    tools = inp.tools
    if tools is None or not tools.has(STARTUPS, "search_jobs"):
        return _answer([], "Startup Jobs", ["Startup Jobs is not connected"])
    profile = _profile(inp)
    _, _, country = _home(profile)
    code = {"india": "IN"}.get(country.lower(), country[:2].upper())
    # The free API only covers the last 14 days.
    after = (date.today() - timedelta(days=min(_int(profile.get("posted within"), 14), 13))).isoformat()
    kind = "internship" if (profile.get("type") or "").lower().startswith("intern") else "full-time"
    phrases = search_phrases(profile)[:4]
    answers = await _within(LANE_SECONDS, [tools.call(
        STARTUPS, "search_jobs", {"q": p, "country": code, "employment_type": kind, "posted_after": after, "limit": 50},
        key=f"startups:{i}", timeout=40) for i, p in enumerate(phrases)])
    jobs, failed = [], []
    for p, a in zip(phrases, answers):
        if a is None or a.is_error:
            failed.append(f"{p}: {'took too long' if a is None else a.text[:120]}")
            continue
        found = (a.structured or {}).get("jobs") if isinstance(a.structured, dict) else None
        jobs += [startup_job(j) for j in (found if isinstance(found, list) else _objects_after(a.text, "jobs"))]
    return _answer(jobs, "Startup Jobs", failed)


# ── LinkedIn ─────────────────────────────────────────────────────────────────

_POSTED = re.compile(r"^(?:Posted|Reposted)\s+(\d+)\s+(minute|hour|day|week|month)s?\s+ago$", re.I)
_NOISE = re.compile(r"^(·|Easy Apply|Promoted|Viewed|Applied|Be an early applicant|Actively reviewing applicants|"
                    r"\d+ applicants?|Over \d+ applicants|\d+ (?:minute|hour|day|week|month)s? ago|.*school alumni.*|"
                    r".*connections? work here|.*benefits?|Your profile matches.*|Actively recruiting)$", re.I)
_PAYLINE = re.compile(r"(₹|INR|\$|USD|€|/yr|/mo|/hr|LPA|lakh)", re.I)


def _ago(n: int, unit: str) -> str:
    days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}[unit.lower()] * n
    return (date.today() - timedelta(days=days)).isoformat()


_SEEN_MARK = re.compile(r"^(Viewed|Applied|Saved)$", re.I)


def linkedin_jobs(text: str, job_ids: list[str]) -> list[dict]:
    """LinkedIn's search page text -> one job per result, in page order, matched to ``job_ids`` (the same order).
    Each result ends with "Posted <n> <unit> ago" – or "Viewed" / "Applied" for one the person has opened; before
    that: the title (often twice), company, place, maybe pay."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    jobs, current = [], []

    def close(posted: str) -> None:
        lines = [x for x in current if not _NOISE.match(x.splitlines()[0].strip())]
        current.clear()
        if len(lines) < 3:
            # A "Posted" line right after a "Viewed" one belongs to the job just read.
            if not lines and posted and jobs and not jobs[-1]["posted"]:
                jobs[-1]["posted"] = posted
            return
        title_block, company, place = lines[-3], lines[-2], lines[-1]
        pay = ""
        if _PAYLINE.search(place) and len(lines) >= 4:
            pay, title_block, company, place = place, lines[-4], lines[-3], lines[-2]
        title = re.sub(r"\s*\(Verified job\)\s*$", "", title_block.splitlines()[-1].strip())
        work = re.search(r"\((On-site|Remote|Hybrid)\)", place)
        jobs.append({"role": title, "company": company.splitlines()[0].strip(),
                     "location": re.sub(r"\s*\((On-site|Remote|Hybrid)\)", "", place).strip(),
                     "work_type": work.group(1).lower() if work else "", "pay": pay, "posted": posted})

    for b in blocks:
        first = b.splitlines()[0].strip()
        m = _POSTED.match(first)
        if m:
            close(_ago(int(m.group(1)), m.group(2)))
        elif _SEEN_MARK.match(first):
            close("")
        else:
            current.append(b)
    # Matched to the ids only when every result was read: a shifted list would give jobs each other's links.
    if len(jobs) != len(job_ids):
        return []
    for j, jid in zip(jobs, job_ids):
        j.update({"url": f"https://www.linkedin.com/jobs/view/{jid}/", "job_id": jid, "job_type": "",
                  "deadline": "", "experience": "", "requirements": "", "source": "LinkedIn"})
    return jobs


def _linkedin_level(profile: dict) -> str:
    seniority = (profile.get("seniority") or "").lower()
    if (profile.get("type") or "").lower().startswith("intern"):
        return "internship"
    return {"fresher": "entry", "junior": "entry,associate", "mid": "associate,mid_senior"}.get(seniority, "entry,associate")


@register("lane_linkedin")
async def lane_linkedin(inp: CodeInput) -> CodeResult:
    tools = inp.tools
    if tools is None or not tools.has(LINKEDIN, "search_jobs"):
        return _answer([], "LinkedIn", ["LinkedIn is not connected"])
    profile = _profile(inp)
    phrases = search_phrases(profile)
    home, city, country = _home(profile)
    nearby = _csv(profile.get("nearby"))
    days = _int(profile.get("posted within"), 14)
    internship = (profile.get("type") or "").lower().startswith("intern")
    base = {"job_type": "internship" if internship else "full_time", "experience_level": _linkedin_level(profile),
            "date_posted": "past_week" if days <= 7 else "past_month", "max_pages": 1}
    searches = [
        {**base, "keywords": phrases[0], "location": city or home, "work_type": "on_site,hybrid"},
        {**base, "keywords": phrases[0], "location": country, "work_type": "remote"},
    ]
    if len(phrases) > 1:
        searches.append({**base, "keywords": phrases[1], "location": (nearby or [city or home])[0], "work_type": "on_site,hybrid"})
    skip = [w.lower() for w in _csv(profile.get("skip titles"))]
    started = asyncio.get_running_loop().time()
    left = lambda: LINKEDIN_SECONDS - (asyncio.get_running_loop().time() - started)  # noqa: E731
    jobs, failed, seen = [], [], set()

    async def one(i: int, args: dict):
        return await asyncio.wait_for(tools.call(LINKEDIN, "search_jobs", args, key=f"linkedin:{i}", timeout=45),
                                      timeout=max(left(), 1))

    for i, args in enumerate(searches):
        if left() < 15:
            break
        try:
            a = await one(i, args)
        except asyncio.TimeoutError:
            failed.append(f"{args['keywords']}: took too long")
            break
        if a.is_error:
            failed.append(f"{args['keywords']}: {a.text[:120]}")
            if re.search(r"429|rate|login|sign in|auth", a.text, re.I):
                break
            continue
        data = a.structured if isinstance(a.structured, dict) else {}
        text = (data.get("sections") or {}).get("search_results") or a.text
        promoted = set(data.get("promoted_job_ids") or [])
        found = linkedin_jobs(text, [str(x) for x in data.get("job_ids") or []])
        if not found and data.get("job_ids"):
            failed.append(f"{args['keywords']}: results couldn't be matched to their links")
        for j in found:
            if j["job_id"] in seen or j["job_id"] in promoted and any(w in j["role"].lower() for w in skip):
                continue
            seen.add(j["job_id"])
            jobs.append(j)

    # The full post of the most promising (not above the level, matching a search word) while time is left.
    words = {w.lower() for p in phrases for w in p.split() if len(w) > 2}
    likely = [j for j in jobs if not any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", j["role"].lower()) for w in skip)]
    likely.sort(key=lambda j: -len(words & set(j["role"].lower().split())))
    for k, j in enumerate(likely[:LINKEDIN_DETAILS]):
        if left() < 6:
            break
        try:
            d = await asyncio.wait_for(tools.call(LINKEDIN, "get_job_details", {"job_id": j["job_id"]},
                                                  key=f"linkedin:job:{j['job_id']}", timeout=20), timeout=max(left(), 1))
        except asyncio.TimeoutError:
            break
        if d.is_error:
            continue
        data = d.structured if isinstance(d.structured, dict) else {}
        post = (data.get("sections") or {}).get("job_posting") or d.text
        about = post.split("About the job", 1)[-1]
        j["requirements"], j["experience"] = requirements_from(about)
        if re.search(r"\bFull-time\b", post):
            j["job_type"] = "full-time"
        elif re.search(r"\bInternship\b", post):
            j["job_type"] = "internship"
    for j in jobs:
        j.pop("job_id", None)
    return _answer(jobs, "LinkedIn", failed)


__all__ = ["jobspy_job", "lane_glassdoor", "lane_indeed", "lane_linkedin", "lane_naukri", "lane_startups", "linkedin_jobs",
           "requirements_from", "sections"]
