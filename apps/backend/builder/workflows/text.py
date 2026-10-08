"""Text plumbing between workflow steps, and the prompts the engine sends.

Ported from the AI Marketplace (``workflows/executor``, ``output_shaping.py``,
``prompts/workflow_runtime.py``, ``connectors/registry``). The prompt wording
is behaviour — it was tuned there against live runs — so it is kept as is.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# ── Joining step outputs ─────────────────────────────────────────────────────


def render_accumulated(parts: list[tuple[str, str]], fallback: str) -> str:
    """One predecessor: its text verbatim. Several: labelled sections, so the
    next step can tell them apart."""
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0][1]
    return "\n\n".join(f"--- {label} ---\n{text}" for label, text in parts)


def fill_placeholders(text: str) -> str:
    return text.replace("{{date}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))


def with_header_footer(text: str, header: str, footer: str) -> str:
    parts = [fill_placeholders(header)] if header else []
    parts.append(text)
    if footer:
        parts.append(fill_placeholders(footer))
    return "\n\n".join(p for p in parts if p)


_FENCE = re.compile(r"^\s*```[\w-]*\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def strip_markdown(text: str) -> str:
    """Markdown -> readable plain text (for SMS / WhatsApp / plain email)."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if _FENCE.match(line) or _TABLE_RULE.match(line):
            continue
        s = line.rstrip()
        s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s)
        s = re.sub(r"^\s{0,3}>\s?", "", s)
        if re.match(r"^\s*([-*_])\s*(\1\s*){2,}$", s):
            continue
        s = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", s)
        if s.strip().startswith("|") and s.strip().endswith("|"):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            s = " — ".join(c for c in cells if c)
        s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
        s = re.sub(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])", r"\2", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ── Tool-step arguments ──────────────────────────────────────────────────────

_CONTENT_HINTS = ("text", "message", "body", "content", "comment", "note", "description", "summary")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def field_tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


def identifier_kind(name: str) -> str | None:
    """Which real-world identifier a field holds (email / phone / url / name), by its name."""
    t = field_tokens(name)
    if t & {"subject", "title", "body", "text", "message", "content", "template", "format", "type",
            "date", "time", "count", "limit", "html"}:
        return None
    if t & {"id", "ids"} and t & {"channel", "user", "recipient", "chat", "thread", "conversation"}:
        return "name"
    if t & {"email", "emails", "recipient", "recipients", "cc", "bcc"} or (t and t <= {"to", "address", "addresses", "list"} and "to" in t):
        return "email"
    if t & {"phone", "mobile", "whatsapp", "msisdn"}:
        return "phone"
    if t & {"url", "urls", "link", "website"}:
        return "url"
    if t & {"channel", "username", "handle"}:
        return "name"
    return None


def is_content_field(name: str) -> bool:
    return identifier_kind(name) is None and any(h in (name or "").lower() for h in _CONTENT_HINTS)


def checked_identifier(kind: str, value, text: str):
    """Keep only identifiers that really appear in the step's text — never one
    the argument mapper made up. None = drop it (a person is asked instead)."""
    hay = (text or "").lower()
    digits_in_text = re.sub(r"\D", "", text or "")

    def ok(item) -> list[str]:
        item = str(item or "").strip()
        if not item:
            return []
        if kind == "email":
            return [e for e in _EMAIL_RE.findall(item) if e.lower() in hay]
        if kind == "url":
            return [u for u in _URL_RE.findall(item) if u.lower() in hay]
        if kind == "phone":
            return [p for p in _PHONE_RE.findall(item) if re.sub(r"\D", "", p) and re.sub(r"\D", "", p) in digits_in_text]
        return [item] if item.lower().lstrip("#@") in hay else []

    if isinstance(value, list):
        kept = [v for item in value for v in ok(item)]
        return kept or None
    kept = ok(value)
    return (kept[0] if len(kept) == 1 else ", ".join(kept)) if kept else None


REQUIRED_FIELDS_NOTE = (
    "\n\nEvery REQUIRED field above (except one marked REAL VALUE ONLY — see the next rule) must be "
    "present in your JSON output — never omit one, even when the text doesn't spell out its content "
    "explicitly. If a required field isn't stated directly, fill it with the text itself (or a clear "
    "summary of it) rather than leaving it out; the tool call fails outright if a required field is "
    "missing. Optional fields may still be omitted when nothing in the text fills them."
)
IDENTIFIER_FIELDS_NOTE = (
    "\n\nFor any field marked REAL VALUE ONLY above (an email address, phone number, URL, username, or "
    "similar identifier): never invent, guess, or synthesize one — not even a plausible-looking "
    "placeholder — even though the rule above says a required field must never be left blank. Use one "
    "only if it appears explicitly, verbatim, in the text below. If none of these fields has a real "
    "value present in the text, omit that field entirely; a person is asked to supply it rather than "
    "the call going out to a fabricated destination."
)


def tool_arguments_prompt(tool_name: str, tool_description: str, field_lines: str, required_note: str, identifier_note: str, text: str) -> str:
    return (
        f"A workflow step is calling the tool \"{tool_name}\" ({tool_description}).\n"
        f"Given the text below, produce ONLY a JSON object with these fields:\n"
        f"{field_lines}{required_note}{identifier_note}\n\nText:\n{text}"
    )


# ── Conditions ───────────────────────────────────────────────────────────────

NONE_OF_THESE = "none of these"


def condition_branch_prompt(options: str, text: str, *, criteria: str | None = None, allow_none: bool = False) -> str:
    criteria_block = f"Instructions from the workflow author:\n{criteria}\n\n" if (criteria and criteria.strip()) else ""
    none_option = f'\n- "{NONE_OF_THESE}"' if allow_none else ""
    none_rule = f'Pick "{NONE_OF_THESE}" only when the text clearly fits none of the other labels.\n\n' if allow_none else ""
    return (
        "A workflow branches here based on the result of the previous step. "
        "Pick exactly one of these outcome labels that best matches the text below.\n\n"
        "Judge the SUBSTANCE of the result: did the previous step actually produce "
        "the core output it was asked for? Ignore hedges, disclaimers, footnotes, or "
        "cautionary notes it tacked on (e.g. \"clarify as needed\", \"left blank\", "
        "\"let me know if you want more\") — LLM steps add this kind of caveat as a "
        "matter of style even when the real result is complete and usable, and a "
        "caveat alone does not mean it failed. Only pick a \"failed\"/\"invalid\"/"
        "\"not ready\"-style label when the core output itself is genuinely missing, "
        "empty, broken, or blocked — not merely because the text mentions a caveat.\n\n"
        f"{criteria_block}"
        f"{none_rule}"
        f"Outcome labels:\n{options}{none_option}\n\n"
        f"Text:\n{text}\n\n"
        'Return ONLY JSON: {"label": "<one of the labels above, verbatim>"}'
    )


# ── Output step ──────────────────────────────────────────────────────────────


def output_language_prompt(text: str, language: str) -> str:
    return (
        f"Rewrite the following workflow answer in {language}. "
        "Keep the exact same markdown structure (headings, bullets, bold, tables, code blocks) "
        "and preserve every `[n]` citation marker verbatim in its original position — do not renumber, "
        "remove, or move them. Translate only the natural-language prose. "
        "Output only the rewritten answer, nothing else.\n\n"
        f"Answer:\n{text}"
    )


def output_compose_prompt(parts: list[str], request: str, language: str | None) -> str:
    lang = f"Write it in {language}." if language else "Write it in the same language as the user's request."
    blocks = "\n\n".join(f"<part {i}>\n{p}\n</part {i}>" for i, p in enumerate(parts, start=1))
    return (
        "Several steps of a workflow each produced part of the answer to the user's request below. "
        "Combine them into ONE clear, well-organized answer to that request.\n\n"
        f"User's request:\n{request}\n\n"
        f"Parts:\n{blocks}\n\n"
        "Rules:\n"
        "- Use ONLY information that is in the parts — never add facts, numbers, names, or links.\n"
        "- Merge overlapping content once, but keep every distinct record and every field it has "
        "(names, titles, emails, phones, scores, dates) — negative findings too. A wider table is fine; lost data is not.\n"
        "- Every `[n]` citation marker stays with the exact fact it came with. Never drop one, "
        "never attach it to a different fact, never renumber or invent one.\n"
        "- Never mention steps, parts, nodes, agents or the workflow itself; drop any part that only says "
        "the request doesn't apply to it or that it had nothing to do.\n"
        "- Do not add a sources/references section.\n"
        f"- {lang}\n"
        "Output only the answer."
    )


FORMATTED_SECTIONS = {
    "summary": ("Summary", "2-3 sentences that directly answer the request."),
    "key_points": ("Key points", "3-6 short bullet points with the most important facts."),
    "details": ("Details", "The supporting information, organized; use a table when the content is tabular data."),
    "next_steps": ("Next steps", "Concrete actions as bullets — ONLY if the content implies something to do; otherwise omit this section entirely."),
}


def output_formatted_prompt(text: str, sections: list[str], language: str | None) -> str:
    parts = [f'- "## {FORMATTED_SECTIONS[k][0]}": {FORMATTED_SECTIONS[k][1]}' for k in sections if k in FORMATTED_SECTIONS]
    lang = f"Write it in {language}." if language else "Write it in the same language as the answer."
    return (
        "Rewrite the workflow answer below as a clean, consistently formatted markdown report.\n\n"
        "Start with a short title line: \"# <title>\".\n"
        "Then these sections, in this order, each with its own \"##\" heading:\n"
        + "\n".join(parts) + "\n\n"
        "Rules:\n"
        "- Use ONLY information that is in the answer — never add facts, numbers, or links.\n"
        "- Every `[n]` citation marker stays with the exact fact it came with.\n"
        "- Skip a section entirely (heading too) when the answer has nothing for it.\n"
        "- Do not add a sources/references section.\n"
        f"- {lang}\n"
        "Output only the report.\n\n"
        f"Answer:\n{text}"
    )


def output_json_prompt(text: str, language: str | None) -> str:
    lang = f" Write any natural-language values in {language}." if language else ""
    return (
        "Convert the workflow answer below into ONE JSON object that captures all of its information "
        "with clear, snake_case keys (use arrays for lists, numbers for numeric values)."
        " Use ONLY information in the answer — never invent values; use null for something the answer "
        f"mentions but leaves unknown.{lang} Return only the JSON object.\n\n"
        f"Answer:\n{text}"
    )


def strip_json_fence(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()
