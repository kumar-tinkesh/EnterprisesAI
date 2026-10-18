"""An `output` node's config (WorkflowNode.output_config): its shape and validation.

Ported from the AI Marketplace (app/workflows/output_shaping.py) — the config
part only; applying it to a run's answer lands with the executor.

  {"format": "markdown" | "formatted" | "text" | "json",   # default "markdown"
   "sections": ["summary", "key_points", "details", "next_steps"],   # "formatted" only
   "language": "Hindi" | null,       # null = same language as the answer
   "header": "…", "footer": "…",     # optional text above/below; ignored for "json"
   "compose": "auto" | "off",        # default "auto" — see below
   "title": "…",                     # "formatted": the report's own title ({{date}} allowed); empty = from the answer
   "custom_sections": [{"title": "Ranked leads", "hint": "one table: rank, company, score"}, …],
                                     # "formatted": your own headings, in order, instead of ``sections``
   "instructions": "…"}              # how to shape it, in words ("max 10 leads, keep every URL");
                                     # used by every AI call here, and makes markdown/text get one too

  compose   — when 2+ steps reach the output (parallel branches), "auto" makes one
              AI call that merges their texts into ONE clean answer (markdown and
              text formats only; formatted/json already make their own call).
              A single step's answer is used as written. "off" = plain join.

  markdown  — the answer as the steps wrote it (no extra AI call, unless ``instructions`` ask for a shape).
  formatted — one AI call re-lays it out as Title / Summary / Key points / Details / Next steps,
              or under your own ``custom_sections``.
  text      — markdown markers stripped (no AI call) — for SMS / WhatsApp / email.
  json      — one AI call (JSON mode) turns it into a JSON object; falls back to markdown if that fails.

Sources are always collected from the steps and returned alongside (never a
setting — `[n]` markers without their list are useless).

Configs written before 2026-09-23 ("template" with {{output}}, "include_sources",
"save_to_file", format "text" meaning raw passthrough) are read too: the template
becomes header/footer; the other two are dropped (files are a Tool Call step's job).
"""
from __future__ import annotations


FORMATS = ("markdown", "formatted", "text", "json")
COMPOSE_MODES = ("auto", "off")
SECTIONS = ("summary", "key_points", "details", "next_steps")
MAX_LANGUAGE = 40
MAX_HEADER_FOOTER = 2000
MAX_TITLE = 200
MAX_INSTRUCTIONS = 2000
MAX_CUSTOM_SECTIONS = 12
MAX_SECTION_TITLE = 80
MAX_SECTION_HINT = 400


def _custom_sections(raw) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("title"), str) and item["title"].strip():
            hint = item.get("hint") if isinstance(item.get("hint"), str) else ""
            out.append({"title": item["title"].strip(), "hint": hint.strip()})
    return out[:MAX_CUSTOM_SECTIONS]


def normalize_output_config(oc: dict | None) -> dict:
    oc = oc if isinstance(oc, dict) else {}
    fmt = str(oc.get("format") or "markdown").strip().lower()
    if fmt not in FORMATS:
        fmt = "markdown"
    sections = oc.get("sections")
    if not isinstance(sections, list) or not sections:
        sections = list(SECTIONS)
    sections = [s for s in SECTIONS if s in sections] or list(SECTIONS)
    language = oc.get("language")
    language = language.strip() if isinstance(language, str) and language.strip() else None
    header = oc.get("header") if isinstance(oc.get("header"), str) else ""
    footer = oc.get("footer") if isinstance(oc.get("footer"), str) else ""
    template = oc.get("template")
    if not header and not footer and isinstance(template, str) and "{{output}}" in template:
        header, _, footer = template.partition("{{output}}")
    compose = str(oc.get("compose") or "auto").strip().lower()
    if compose not in COMPOSE_MODES:
        compose = "auto"
    title = oc.get("title") if isinstance(oc.get("title"), str) else ""
    instructions = oc.get("instructions") if isinstance(oc.get("instructions"), str) else ""
    return {
        "format": fmt, "sections": sections, "language": language,
        "header": header.strip(), "footer": footer.strip(), "compose": compose,
        "title": title.strip(), "custom_sections": _custom_sections(oc.get("custom_sections")),
        "instructions": instructions.strip(),
    }


def config_problem(oc: dict | None) -> str | None:
    """Why this output_config can't be saved, or None."""
    if oc is None:
        return None
    if not isinstance(oc, dict):
        return "configuration must be an object"
    fmt = oc.get("format")
    if fmt is not None and fmt not in FORMATS:
        return f"format must be one of {', '.join(FORMATS)}"
    sections = oc.get("sections")
    if sections is not None:
        if not isinstance(sections, list) or any(s not in SECTIONS for s in sections):
            return f"sections can only be {', '.join(SECTIONS)}"
        if fmt == "formatted" and not sections and not oc.get("custom_sections"):
            return "pick at least one section for the formatted layout"
    compose = oc.get("compose")
    if compose is not None and compose not in COMPOSE_MODES:
        return f"compose must be one of {', '.join(COMPOSE_MODES)}"
    lang = oc.get("language")
    if lang is not None and (not isinstance(lang, str) or len(lang.strip()) > MAX_LANGUAGE):
        return "language must be a language name"
    for key, limit in (("header", MAX_HEADER_FOOTER), ("footer", MAX_HEADER_FOOTER), ("title", MAX_TITLE), ("instructions", MAX_INSTRUCTIONS)):
        v = oc.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > limit):
            return f"{key} must be text of at most {limit} characters"
    custom = oc.get("custom_sections")
    if custom is not None:
        if not isinstance(custom, list) or len(custom) > MAX_CUSTOM_SECTIONS:
            return f"custom sections must be a list of at most {MAX_CUSTOM_SECTIONS}"
        for item in custom:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
                return "each custom section needs a title"
            if len(item["title"]) > MAX_SECTION_TITLE:
                return f"a custom section title can be at most {MAX_SECTION_TITLE} characters"
            hint = item.get("hint")
            if hint is not None and (not isinstance(hint, str) or len(hint) > MAX_SECTION_HINT):
                return f"what goes in a custom section can be at most {MAX_SECTION_HINT} characters"
    return None
