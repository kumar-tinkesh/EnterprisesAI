"""The job finder's code steps that call tools themselves (``builder.workflows.code_steps``, ``tool_needs``): fixed
calls the template knows in advance, so no AI turn decides them – faster, and nothing gets miscopied.

* ``job_seen``      the tracker sheet's Apply URLs (so a job isn't found twice) and its rows (the ones still open
                    fill the report's top list on a day with few new posts).
* ``job_contacts``  for the best matches: hiring emails printed on the post or the company's careers pages (Tavily),
                    and recruiters LinkedIn names in full (one search each for the top few, time-boxed) – kept only
                    when the email is the company's own hiring address (``job_finder_steps.hiring_email``).
* ``job_tracker``   every 50+ match the sheet doesn't have yet (and the lower matches the top list showed), in ONE
                    update (the sheet is made when there is none).
* ``job_drafts``    each cover letter as a Gmail draft – never sent; to the recruiter's address, else your own.
* ``job_whatsapp``  the short summary to the number in the WhatsApp field – or, when it's empty, the resume's number
                    as a suggestion the person can change – a send, so it always asks first.

``ask_before_saving`` (an input field, read by the Report) makes the tracker update and every draft wait for a yes.
"""
from __future__ import annotations

import asyncio
import json
import re

from builder.templates.job_finder_steps import (
    NOTE, TRACKER, TRACKER_COLUMNS, _key, hiring_email, json_objects, norm_url, sections,
)
from builder.runs.db import is_transient
from builder.workflows.code_steps import CodeInput, CodeResult, StepTools, register

SHEETS, GMAIL, WHATSAPP, TAVILY, LINKEDIN = "Google Sheets", "Gmail", "WhatsApp", "Tavily", "LinkedIn"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# The companies worth looking up, and how long the lookups may take together.
CONTACT_COMPANIES, CONTACT_MIN_SCORE, CONTACT_SECONDS = 8, 60, 45
LINKEDIN_PEOPLE = 3


def _payload(inp: CodeInput, key: str) -> dict:
    """The JSON document a code step before this one routed here (the one that has ``key``)."""
    for _, text in sections(inp.parts):
        stripped = text.strip()
        if stripped.startswith("{") and f'"{key}"' in stripped:
            try:
                return json.loads(stripped)
            except ValueError:
                continue
    return {}


def _dicts(answer_text: str, structured: dict | None) -> list[dict]:
    """Every JSON object a tool answered with: its structured content's, or the text's (one or more documents)."""
    out: list[dict] = []
    if isinstance(structured, dict):
        inner = structured.get("result", structured)
        out += [d for d in (inner if isinstance(inner, list) else [inner]) if isinstance(d, dict)]
        if out:
            return out
    decoder, text, i = json.JSONDecoder(), answer_text or "", 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end


# ── The tracker sheet ────────────────────────────────────────────────────────


async def _find_tracker(tools: StepTools, prefix: str) -> tuple[str, str, list[list]] | None:
    """The sheet called exactly TRACKER -> (spreadsheet id, first sheet's name, its rows); None when there is none."""
    found = await tools.call(SHEETS, "search_spreadsheets", {"query": TRACKER}, key=f"{prefix}:search", timeout=30)
    if found.is_error:
        raise RuntimeError(found.text[:300])
    sheet = next((d for d in _dicts(found.text, found.structured) if d.get("name") == TRACKER and d.get("id")), None)
    if sheet is None:
        return None
    sid = sheet["id"]
    return sid, *(await _first_sheet(tools, sid, prefix))


async def _first_sheet(tools: StepTools, sid: str, prefix: str) -> tuple[str, list[list]]:
    listed = await tools.call(SHEETS, "list_sheets", {"spreadsheet_id": sid}, key=f"{prefix}:sheets", timeout=30)
    names = (listed.structured or {}).get("result") if isinstance(listed.structured, dict) else None
    if isinstance(names, list) and names:
        name = str(names[0])
    else:
        name = next((ln.strip().strip('"[],') for ln in listed.text.splitlines() if ln.strip().strip('"[],')), "Sheet1")
    data = await tools.call(SHEETS, "get_sheet_data", {"spreadsheet_id": sid, "sheet": name}, key=f"{prefix}:read", timeout=30)
    if data.is_error:
        raise RuntimeError(data.text[:300])
    rows: list[list] = []
    for d in _dicts(data.text, data.structured):
        for vr in d.get("valueRanges") or []:
            rows += vr.get("values") or []
        rows += d.get("values") or []
    return name, rows


def _link(sid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sid}"


@register("job_seen")
async def job_seen(inp: CodeInput) -> CodeResult:
    none = CodeResult(output="SEEN\nnone")
    if inp.tools is None or not inp.tools.has(SHEETS, "search_spreadsheets"):
        return none
    try:
        found = await _find_tracker(inp.tools, "seen")
    except RuntimeError:
        return none
    if found is None:
        return none
    rows = found[2]
    head = [str(h) for h in (rows[0] if rows else [])] or list(TRACKER_COLUMNS)
    urls = [str(r[8]) for r in rows[1:] if len(r) > 8 and str(r[8]).startswith("http")]
    # Every row too (one JSON object each, by heading): the report shows the ones still open again.
    tracked = [json.dumps({h: (r[i] if i < len(r) else "") for i, h in enumerate(head)}, ensure_ascii=False)
               for r in rows[1:] if len(r) > 8 and str(r[8]).startswith("http")]
    return CodeResult(output="SEEN\n" + ("\n".join(urls) or "none") + ("\n" + "\n".join(tracked) if tracked else ""))


@register("job_tracker")
async def job_tracker(inp: CodeInput) -> CodeResult:
    report = _payload(inp, "drafts")
    tools = inp.tools
    if tools is None or not tools.has(SHEETS, "update_cells"):
        return CodeResult(output="Tracker: Google Sheets is not connected – nothing saved.")
    ask = bool(report.get("ask"))
    try:
        found = await _find_tracker(tools, "tracker")
        if found is None:
            made = await tools.call(SHEETS, "create_spreadsheet", {"title": TRACKER}, key="tracker:create", ask=ask)
            if made.is_error or made.declined:
                return CodeResult(output=f"Tracker: couldn't make the sheet – {made.text[:300]}")
            sid = next((str(d.get("spreadsheetId") or d.get("id")) for d in _dicts(made.text, made.structured)
                        if d.get("spreadsheetId") or d.get("id")), "")
            if not sid:
                return CodeResult(output=f"Tracker: couldn't read the new sheet's id – {made.text[:300]}")
            name, rows = await _first_sheet(tools, sid, "tracker:new")
        else:
            sid, name, rows = found
    except RuntimeError as exc:
        return CodeResult(output=f"Tracker: {exc}")

    if not rows:
        head = await tools.call(SHEETS, "update_cells", {"spreadsheet_id": sid, "sheet": name, "range": "A1:M1",
                                                         "data": [list(TRACKER_COLUMNS)]}, key="tracker:header", ask=ask)
        if head.is_error:
            return CodeResult(output=f"Tracker: {head.text[:300]}")
        rows = [list(TRACKER_COLUMNS)]
    elif len(rows[0]) < len(TRACKER_COLUMNS):
        # An older tracker (before contacts): add the missing headings.
        start = len(rows[0])
        cols = "ABCDEFGHIJKLM"
        await tools.call(SHEETS, "update_cells", {"spreadsheet_id": sid, "sheet": name,
                                                  "range": f"{cols[start]}1:M1", "data": [list(TRACKER_COLUMNS[start:])]},
                         key="tracker:columns", ask=ask)

    have = {norm_url(str(r[8])) for r in rows[1:] if len(r) > 8}
    new = []
    for status, jobs in (("New", report.get("top") or []), ("Extra", report.get("extra") or []),
                         ("Lower match", report.get("low") or [])):
        for j in jobs:
            if norm_url(j.get("url", "")) in have:
                continue
            have.add(norm_url(j.get("url", "")))
            new.append([report.get("date", ""), j.get("company", ""), j.get("role", ""), j.get("location", ""),
                        j.get("job_type", ""), j.get("pay", ""), str(j.get("score", "")), j.get("deadline", ""),
                        j.get("url", ""), status, j.get("source", ""), j.get("contact", ""), j.get("contact_link", "")])
    if not new:
        return CodeResult(output=f"Tracker: no new jobs – {_link(sid)}")
    n = len(rows)
    done = await tools.call(SHEETS, "update_cells", {"spreadsheet_id": sid, "sheet": name,
                                                     "range": f"A{n + 1}:M{n + len(new)}", "data": new},
                            key="tracker:rows", ask=ask)
    if done.declined:
        return CodeResult(output=f"Tracker: not saved – you chose not to add the {len(new)} rows.")
    if done.is_error:
        return CodeResult(output=f"Tracker: {done.text[:300]}")
    return CodeResult(output=f"Tracker: {len(new)} new jobs added – {_link(sid)}")


# ── Gmail drafts ─────────────────────────────────────────────────────────────


@register("job_drafts")
async def job_drafts(inp: CodeInput) -> CodeResult:
    report = _payload(inp, "drafts")
    drafts = report.get("drafts") or []
    if not drafts:
        return CodeResult(output="Gmail: no cover letters to save.")
    tools = inp.tools
    if tools is None or not tools.has(GMAIL, "create_draft"):
        return CodeResult(output="Gmail is not connected – drafts skipped.")
    me = await tools.call(GMAIL, "get_profile", {}, key="drafts:me", timeout=30)
    own = next(iter(_EMAIL.findall(me.text or "")), "")
    saved, problems = [], []
    for i, d in enumerate(drafts):
        to = d.get("to") if _EMAIL.fullmatch(d.get("to") or "") else own
        if not to:
            problems.append(f"{d.get('heading')}: no address to put it under")
            continue
        out = await tools.call(GMAIL, "create_draft", {"to": to, "subject": d.get("subject", ""), "body_text": d.get("body", "")},
                               key=f"drafts:{i}", timeout=60, ask=bool(report.get("ask")))
        if out.is_error or out.declined:
            problems.append(f"{d.get('heading')}: {'not saved – you said no' if out.declined else out.text[:200]}")
        else:
            saved.append(f"{d.get('heading')}" + ("" if to == own else f" (to {to})"))
    lines = [f"Gmail: {len(saved)} drafts saved", *saved] + ([f"Not saved: {p}" for p in problems])
    return CodeResult(output="\n".join(lines))


# ── WhatsApp ─────────────────────────────────────────────────────────────────


@register("job_whatsapp")
async def job_whatsapp(inp: CodeInput) -> CodeResult:
    alert = _payload(inp, "drafts").get("whatsapp") or {}
    if not alert.get("to"):
        return CodeResult(output="WhatsApp: no number given – skipped.")
    if not alert.get("message"):
        return CodeResult(output="WhatsApp: no matches today – nothing sent.")
    tools = inp.tools
    if tools is None or not tools.has(WHATSAPP, "send_message"):
        return CodeResult(output="WhatsApp is not connected – skipped.")
    # A message to someone: it always asks first (builder.runs.tool_calls) – and a number from the resume is only a
    # suggestion: the person can change it there before saying yes.
    note = ("the number is from your resume – change it here to send to another number, or don't send"
            if alert.get("from_resume") else "")
    out = await tools.call(WHATSAPP, "send_message", {"recipient": alert["to"], "message": alert["message"]},
                           key="whatsapp:send", timeout=60, note=note)
    if out.declined:
        return CodeResult(output="WhatsApp: not sent – you chose not to send it.\n\n" + alert["message"])
    if out.is_error:
        return CodeResult(output=f"WhatsApp: {out.text[:300]}")
    sent_to = str((out.arguments or {}).get("recipient") or alert["to"])
    return CodeResult(output=f"WhatsApp: sent to {sent_to}")


# ── Recruiters and hiring emails ─────────────────────────────────────────────


def _people(text: str, structured: dict | None, company: str) -> list[dict]:
    """LinkedIn's people results -> recruiters at this company that LinkedIn names in full ("LinkedIn Member" is
    someone hidden – no use), each with their profile link when the results carry one."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    links = re.findall(r"/in/[A-Za-z0-9\-_%]+", json.dumps(structured or {}) + (text or ""))
    words = [w for w in re.split(r"[^a-z0-9]+", company.lower()) if len(w) >= 3]
    out = []
    for i, b in enumerate(blocks):
        if b != "View" or i < 3:
            continue
        name, headline = blocks[i - 3], blocks[i - 2]
        current = blocks[i + 1] if i + 1 < len(blocks) and blocks[i + 1].startswith(("Current:", "Past:")) else ""
        about = f"{headline} {current}".lower()
        if name == "LinkedIn Member" or len(name) > 60 or current.startswith("Past:"):
            continue
        if not re.search(r"recruit|talent|\bhr\b|hiring|people", about) or not any(w in about for w in words):
            continue
        tokens = [t for t in re.split(r"[^a-z]+", name.lower()) if len(t) >= 3]
        link = next((f"https://www.linkedin.com{u}" for u in links if tokens and all(t in u.lower() for t in tokens[:2])), "")
        out.append({"name": name, "title": headline[:80], "link": link})
    return out


async def _emails(tools: StepTools, jobs: list[dict]) -> dict[str, tuple[str, str]]:
    """{company key: (hiring email, the page it was printed on)} from the posts themselves and a careers search."""
    found: dict[str, tuple[str, str]] = {}

    def take(company: str, text: str, page: str) -> None:
        for email in _EMAIL.findall(text or ""):
            if hiring_email(email, company) and _key(company) not in found:
                found[_key(company)] = (email, page)

    calls = []
    if tools.has(TAVILY, "tavily_extract"):
        urls = [j["url"] for j in jobs if j.get("url")][:CONTACT_COMPANIES]
        calls.append(("extract", tools.call(TAVILY, "tavily_extract", {"urls": urls}, key="contacts:posts", timeout=30)))
    if tools.has(TAVILY, "tavily_search"):
        for i, j in enumerate(jobs):
            calls.append((j["company"], tools.call(
                TAVILY, "tavily_search", {"query": f"{j['company']} careers hiring email HR India", "max_results": 5},
                key=f"contacts:mail:{i}", timeout=25)))
    answers = await asyncio.gather(*(c for _, c in calls), return_exceptions=True)
    for (what, _), answer in zip(calls, answers):
        if isinstance(answer, BaseException) or answer.is_error:
            continue
        if what == "extract":
            # One block per page ("URL: …"): an email on a post belongs to that post's company.
            for block in re.split(r"(?=^URL: )", answer.text, flags=re.M):
                page = (re.match(r"URL: (\S+)", block) or [None, ""])[1]
                job = next((j for j in jobs if page and norm_url(j["url"]) == norm_url(page)), None)
                if job:
                    take(job["company"], block, page)
        else:
            for block in re.split(r"(?=^Title: )", answer.text, flags=re.M):
                page = (re.search(r"^URL: (\S+)", block, re.M) or [None, ""])[1]
                take(what, block, page)
    return found


async def _recruiters(tools: StepTools, jobs: list[dict], home: str) -> dict[str, dict]:
    """One LinkedIn people search per company for the top few, one at a time (LinkedIn answers a burst with 429)."""
    out: dict[str, dict] = {}
    if not tools.has(LINKEDIN, "search_people"):
        return out
    for i, j in enumerate(jobs[:LINKEDIN_PEOPLE]):
        answer = await tools.call(LINKEDIN, "search_people", {"keywords": f"recruiter {j['company']}", "location": home},
                                  key=f"contacts:people:{i}", timeout=30)
        if answer.is_error:
            if re.search(r"429|rate|login|sign in", answer.text, re.I):
                break
            continue
        people = _people(answer.text, answer.structured, j["company"])
        if people:
            out[_key(j["company"])] = people[0]
    return out


@register("job_contacts")
async def job_contacts(inp: CodeInput) -> CodeResult:
    ranked = _payload(inp, "top")
    profile = ranked.get("profile") or {}
    seen, jobs = set(), []
    for j in sorted(ranked.get("top") or [], key=lambda j: -j.get("score", 0)):
        if j.get("score", 0) >= CONTACT_MIN_SCORE and _key(j["company"]) not in seen:
            seen.add(_key(j["company"]))
            jobs.append(j)
    jobs = jobs[:CONTACT_COMPANIES]
    tools = inp.tools
    if not jobs or tools is None:
        return CodeResult(output=f"{NOTE}No contacts looked up" + ("" if jobs else " – no match scored 60+"))
    home = (profile.get("home") or "").split(",")[0].strip()
    # Both kinds of lookup at once, and together never longer than CONTACT_SECONDS: what's found by then is kept.
    mail_task = asyncio.ensure_future(_emails(tools, jobs))
    people_task = asyncio.ensure_future(_recruiters(tools, jobs, home))
    done, pending = await asyncio.wait({mail_task, people_task}, timeout=CONTACT_SECONDS)
    for task in pending:
        task.cancel()
    for task in done:
        if task.exception() is not None and is_transient(task.exception()):
            raise task.exception()
    emails = mail_task.result() if mail_task in done and not mail_task.exception() else {}
    people = people_task.result() if people_task in done and not people_task.exception() else {}
    lines, n_people, n_mail = [], 0, 0
    for j in jobs:
        k = _key(j["company"])
        person, mail = people.get(k), emails.get(k)
        if not person and not mail:
            continue
        n_people += bool(person)
        n_mail += bool(mail)
        lines.append(json.dumps({
            "company": j["company"], "role": j["role"], "name": (person or {}).get("name", ""),
            "title": (person or {}).get("title", ""), "email": mail[0] if mail else "",
            "link": (person or {}).get("link") or (mail[1] if mail else ""),
            "source": "LinkedIn" if person else "the post or careers page",
        }, ensure_ascii=False))
    lines.append(f"{NOTE}Found {n_people} recruiters and {n_mail} hiring emails for {len(jobs)} companies")
    return CodeResult(output="\n".join(lines))


__all__ = ["job_contacts", "job_drafts", "job_seen", "job_tracker", "job_whatsapp", "json_objects"]
