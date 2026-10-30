"""The job finder's code steps (``builder.workflows.code_steps``): what needs no AI, done in code – fast, the same
every time, and it never drops or miscopies a row the way a model does with a long table.

* ``job_filter``  the search lanes' JSON lines -> one list: duplicates merged, old / closed / fee-asking / skipped
                  titles / jobs already in the tracker dropped, the 100 most relevant kept, split into one batch per
                  Matcher (``routed``) and the whole list for Rank.
* ``job_rank``    the Matchers' scores -> every job scoring 50+, nearest first, the top ``Target`` kept as matches.
* ``job_report``  ranked jobs + contacts + the writer's skill gaps and letters -> the report the savers read.

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
# What the Matchers read at most – more only makes the report slower, not better.
MAX_SCORED = 100
DEFAULT_TARGET = 25
MIN_SCORE = 50
FEE_WORDS = ("registration fee", "security deposit", "training fee", "kit fee", "joining fee", "refundable deposit",
             "pay to apply", "processing fee")
_TRACKING = re.compile(r"^(utm_.*|ref|refid|trk|trackingid|src|source|from|position|pagenum|origin)$", re.I)
_SECTION = re.compile(r"^--- (.+?) ---$", re.M)
FIELDS = ("company", "role", "location", "work_type", "job_type", "pay", "posted", "deadline", "url", "requirements",
          "source")
_ALIASES = {"title": "role", "job_title": "role", "apply_url": "url", "link": "url", "job_url": "url",
            "found_via": "source", "salary": "pay", "date_posted": "posted"}


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


def _job(raw: dict, lane: str) -> dict:
    job = {f: "" for f in FIELDS}
    for k, v in raw.items():
        k = _ALIASES.get(str(k).lower(), str(k).lower())
        if k in job and v not in (None, [], {}):
            job[k] = (", ".join(map(str, v)) if isinstance(v, list) else str(v)).strip()
    job["source"] = job["source"] or lane
    return job


def _cell(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "/").strip()


# ── Steps ────────────────────────────────────────────────────────────────────


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", text.lower()))


@register("job_filter")
def job_filter(inp: CodeInput) -> CodeResult:
    profile_text = next((t for _, t in inp.parts if "PROFILE" in t), "")
    profile = parse_profile(profile_text)
    today = date.today()
    cutoff = today - timedelta(days=_int(profile.get("posted within"), 14))
    want = (profile.get("type") or "").lower()
    skip_titles = _csv(profile.get("skip titles"))
    excludes = [e.lower() for e in _csv(profile.get("exclude")) if "fee" not in e.lower() and "unpaid" not in e.lower()]
    unpaid_out = "unpaid" in (profile.get("exclude") or "").lower()

    seen: set[str] = set()
    per_lane: dict[str, int] = {}
    found: list[dict] = []
    for label, text in sections([p for p in inp.parts if "PROFILE" not in p[1]]):
        if text.lstrip().startswith("SEEN"):
            seen |= {norm_url(u) for u in re.findall(r"https?://\S+", text)}
            continue
        jobs = [_job(o, label) for o in json_objects(text)]
        per_lane[label] = len(jobs)
        found += jobs

    counts = {"found": len(found), "duplicates": 0, "in_tracker": 0, "old_or_closed": 0, "fee_or_unpaid": 0,
              "title_type_or_excluded": 0, "no_link": 0, "kept": 0, "not_scored": 0}
    by_url: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for job in found:
        url = norm_url(job["url"])
        if not url:
            counts["no_link"] += 1
            continue
        if url in seen:
            counts["in_tracker"] += 1
            continue
        name = _key(job["company"]) + "|" + _key(job["role"])
        twin = by_url.get(url) or (by_name.get(name) if _key(job["company"]) else None)
        if twin is not None:
            counts["duplicates"] += 1
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
        if (posted and posted < cutoff) or (deadline and deadline < today):
            counts["old_or_closed"] += 1
        elif any(w in text for w in FEE_WORDS) or (unpaid_out and "unpaid" in text):
            counts["fee_or_unpaid"] += 1
        elif (any(_has_word(job["role"], w) for w in skip_titles)
              or ("intern" in job["job_type"].lower() and want.startswith("full"))
              or ("full" in job["job_type"].lower() and want.startswith("intern"))
              or any(e in f"{job['company']} {job['role']}".lower() for e in excludes)):
            counts["title_type_or_excluded"] += 1
        else:
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
        lines = "\n".join(json.dumps({k: j[k] for k in ("id", "company", "role", "location", "work_type", "job_type",
                                                         "pay", "posted", "deadline", "requirements")},
                                     ensure_ascii=False) for j in batch)
        routed[target] = f"{block}\n\nJOBS – {len(batch)}, one JSON object per line:\n{lines}"
    payload = json.dumps({"profile": profile, "jobs": kept, "counts": counts, "lanes": per_lane}, ensure_ascii=False)
    for target, kind in inp.targets:
        if kind != "agent":
            routed[target] = payload

    lanes = " · ".join(f"{k} {v}" for k, v in per_lane.items()) or "no search answered"
    dropped = counts["found"] - counts["kept"] - counts["duplicates"] - counts["not_scored"]
    output = (
        f"Found {counts['found']} jobs ({lanes}).\n"
        f"Kept {counts['kept']} to score: {counts['duplicates']} duplicates merged, {counts['in_tracker']} already in "
        f"your tracker, {counts['old_or_closed']} old or closed, {counts['fee_or_unpaid']} asking a fee or unpaid, "
        f"{counts['title_type_or_excluded']} wrong level, type or excluded, {counts['no_link']} without a link"
        + (f", {counts['not_scored']} least relevant left out" if counts["not_scored"] else "") + ".\n"
        f"{NOTE}Checked {counts['found']} jobs: {counts['kept']} new to score, {max(dropped, 0)} dropped, "
        f"{counts['duplicates']} duplicates"
    )
    return CodeResult(output=output, routed=routed)


def _near(profile: dict) -> list[str]:
    """Home's city (not its state or country), the Nearby cities and the Region ("Delhi NCR")."""
    places = _csv(profile.get("home"))[:1] + _csv(profile.get("nearby")) + _csv(profile.get("region"))
    return [p for p in places if p.lower() not in ("india", "remote")]


def _group(job: dict, near: list[str]) -> int:
    where = f"{job['location']} {job['work_type']}".lower()
    if any(p.lower() in where for p in near):
        return 0
    return 1 if "remote" in where or "work from home" in where else 2


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(c for c, _ in columns) + " |\n|" + "---|" * len(columns)
    return head + "".join("\n| " + " | ".join(_cell(r.get(k)) for _, k in columns) + " |" for r in rows)


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
    near = _near(profile)
    target = _int(profile.get("target"), DEFAULT_TARGET)

    matched = []
    for job in jobs:
        s = scores.get(job["id"]) or {}
        score = _int(s.get("score"), 0)
        if score >= MIN_SCORE:
            matched.append({**job, "score": score, "why": str(s.get("why") or ""), "missing": str(s.get("missing") or "")})
    matched.sort(key=lambda j: (_group(j, near), -j["score"]))
    top, extra = matched[:target], matched[target:]
    counts = {**(data.get("counts") or {}), "scored": len(scores), "matched": len(matched)}

    columns = [("Score", "score"), ("Company", "company"), ("Role", "role"), ("Location", "location"),
               ("Type", "job_type"), ("Pay", "pay"), ("Apply URL", "url"), ("Why it fits", "why"),
               ("Missing skills", "missing")]
    table = _table(top, columns) if top else "No job scored 50 or more."
    routed = {}
    for t, kind in inp.targets:
        routed[t] = (json.dumps({"profile": profile, "top": top, "extra": extra, "counts": counts,
                                 "lanes": data.get("lanes") or {}}, ensure_ascii=False)
                     if kind == "code" else f"TOP MATCHES (best first)\n{table}")
    best = f"best: {top[0]['score']} · {top[0]['role']} @ {top[0]['company']}" if top else "none scored 50+"
    output = (f"{table}\n\n{len(extra)} more scored 50+ (they go to the tracker as Extra).\n"
              f"{NOTE}{len(matched)} matches scored 50+ – top {len(top)} in the report, {best}")
    return CodeResult(output=output, routed=routed)


@register("job_report")
def job_report(inp: CodeInput) -> CodeResult:
    ranked: dict = {}
    contacts: dict[str, dict] = {}
    writer = ""
    for _, text in sections(inp.parts):
        stripped = text.strip()
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
                if name.lower() in ("", "none", "none found") and "@" not in email:
                    continue
                key = _key(o["company"])
                # One per company: one with a published email first.
                if key not in contacts or ("@" in email and "@" not in contacts[key]["email"]):
                    contacts[key] = {"name": name, "title": str(o.get("title") or ""), "email": email,
                                     "link": str(o.get("link") or o.get("contact_link") or "")}
            continue
        if "## " in text:
            writer = "\n".join(ln for ln in text.splitlines() if not ln.startswith(NOTE.strip())).strip()

    top, extra = ranked.get("top") or [], ranked.get("extra") or []
    counts, lanes, profile = ranked.get("counts") or {}, ranked.get("lanes") or {}, ranked.get("profile") or {}
    near = _near(profile)
    every = top + extra
    for job in every:
        c = contacts.get(_key(job["company"]))
        if c:
            job["contact"] = f"{c['name']} ({c['title']})" if c["name"] and c["title"] else (c["name"] or c["email"])
            job["contact_link"] = c["link"] or c["email"]

    groups = [_group(j, near) for j in every]
    full_time = sum(1 for j in every if "intern" not in j["job_type"].lower())
    columns = [("Score", "score"), ("Company", "company"), ("Role", "role"), ("Location", "location"),
               ("Type", "job_type"), ("Pay", "pay"), ("Posted", "posted"), ("Deadline", "deadline"),
               ("Apply URL", "url"), ("Why it fits", "why"), ("Missing skills", "missing"), ("Found via", "source"),
               ("Contact", "contact"), ("Contact link", "contact_link")]
    lane_line = " · ".join(f"{k} {v}" for k, v in lanes.items())
    parts = [
        f"# Job matches – {date.today().isoformat()}",
        f"{len(every)} matches scored 50+: {full_time} full-time, {len(every) - full_time} internships · "
        f"{groups.count(0)} near you, {groups.count(1)} remote, {groups.count(2)} elsewhere.",
        f"Searched: {lane_line or 'no source answered'}. {counts.get('found', 0)} found → {counts.get('kept', 0)} new "
        f"after removing duplicates, old posts and jobs already in your tracker → {counts.get('matched', 0)} scored 50+.",
        "## Matches",
        _table(top, columns) if top else "No job scored 50 or more today.",
    ]
    if extra:
        parts += ["## More matches", "Also scored 50+; they go into your tracker with Status \"Extra\".",
                  _table(extra, columns)]
    if writer:
        parts.append(writer)
    best = f" – best: {top[0]['score']} · {top[0]['role']} @ {top[0]['company']}" if top else ""
    parts.append(f"{NOTE}{len(every)} matches{best}")
    return CodeResult(output="\n\n".join(parts))
