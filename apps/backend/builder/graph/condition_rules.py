"""How a `condition` node picks its branch — config shape, rule checks, validation.

Ported unchanged from the AI Marketplace (app/workflows/condition_rules.py).

A condition node decides in one of two ways (WorkflowNode.condition_config):

  {"mode": "ai",   "instructions": "classify by urgency", "default_branch": "<node id>"}
      An AI reads the previous step's result and picks one outgoing line by
      its label ("Approved", "Needs editing", ...). `instructions` is optional
      extra guidance for it.

  {"mode": "rule", "rules": {"<target node id>": {"field": "text", "op": "contains", "value": "urgent"}},
   "default_branch": "<node id>"}
      No AI: each outgoing line has a plain rule, checked top to bottom; the
      first that matches wins.

Either way, when nothing matches the run goes to `default_branch`, else the
first line WITHOUT a label/rule (the "otherwise" line), else the first line.

Rules are data, never code — there is no eval anywhere here. (This replaced a
Python-expression mode on 2026-09-23: too technical for users, and an
allow-listed eval still let a rule like `text * 10**9`-style blow up memory.)

Configs written before this ("evaluation_mode": auto/llm/keyword/expression,
"criteria", "timeout_seconds") are still read: auto/llm/expression -> ai,
keyword -> rule with a `contains <label>` rule per labelled line.
"""
from __future__ import annotations

import json
import re
from typing import Any

MODES = ("ai", "rule")

# op -> short phrase for labels/summaries
OPS: dict[str, str] = {
    "contains": "contains",
    "not_contains": "doesn't contain",
    "equals": "is",
    "not_equals": "is not",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
    "is_empty": "is empty",
    "is_not_empty": "is not empty",
}
NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
NO_VALUE_OPS = {"is_empty", "is_not_empty"}
MAX_INSTRUCTIONS = 1000

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")


def normalize_condition_config(cc: dict | None, out_edges: list[dict] | None = None) -> dict:
    """Any stored condition_config (new or pre-2026-09-23) -> the one shape
    routing reads: {"mode", "instructions", "default_branch", "rules"}."""
    cc = cc if isinstance(cc, dict) else {}
    raw_mode = str(cc.get("mode") or cc.get("evaluation_mode") or "ai").strip().lower()
    mode = "rule" if raw_mode in ("rule", "keyword") else "ai"
    instructions = cc.get("instructions")
    if instructions is None:
        instructions = cc.get("criteria")
    instructions = str(instructions).strip() if isinstance(instructions, str) and instructions.strip() else None
    default_branch = str(cc.get("default_branch") or "").strip() or None

    rules: dict[str, dict] = {}
    for target, rule in (cc.get("rules") or {}).items() if isinstance(cc.get("rules"), dict) else []:
        if isinstance(rule, dict) and rule.get("op"):
            rules[str(target)] = rule
    if raw_mode == "keyword":
        # Legacy keyword mode matched each label as a substring — the same thing as a contains rule.
        for e in out_edges or []:
            label = (e.get("condition") or "").strip()
            if label and e.get("target") not in rules:
                rules[e["target"]] = {"field": "text", "op": "contains", "value": label}
    return {"mode": mode, "instructions": instructions, "default_branch": default_branch, "rules": rules}


def _json_from_text(text: str) -> Any:
    """The previous step's result as JSON, if it is JSON (a ```json fence is fine too)."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def field_value(field: str | None, text: str) -> Any:
    """`text` (or empty) -> the whole previous result. Anything else is a JSON
    field path ("amount", "customer.name", "items.0"); None when the result
    isn't JSON or has no such field."""
    field = (field or "text").strip()
    if field in ("", "text"):
        return text or ""
    value = _json_from_text(text)
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMBER_RE.search(str(value or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def eval_rule(rule: dict | None, text: str) -> bool:
    """Does the previous step's result satisfy this rule? Never raises — a
    rule that can't be checked (missing field, non-number) just doesn't match."""
    if not isinstance(rule, dict):
        return False
    op = rule.get("op")
    if op not in OPS:
        return False
    actual = field_value(rule.get("field"), text)

    if op in NO_VALUE_OPS:
        empty = actual is None or (isinstance(actual, (str, list, dict)) and len(actual if not isinstance(actual, str) else actual.strip()) == 0)
        return empty if op == "is_empty" else not empty

    if op in NUMERIC_OPS:
        a, b = _as_number(actual), _as_number(rule.get("value"))
        if a is None or b is None:
            return False
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]

    have = _as_text(actual).strip().lower()
    want = _as_text(rule.get("value")).strip().lower()
    if op == "contains":
        return bool(want) and want in have
    if op == "not_contains":
        return not want or want not in have
    if op == "equals":
        return have == want
    if op == "not_equals":
        return have != want
    if op == "starts_with":
        return bool(want) and have.startswith(want)
    if op == "ends_with":
        return bool(want) and have.endswith(want)
    return False


def rule_problem(rule: Any) -> str | None:
    """Why this rule can't be saved, or None."""
    if not isinstance(rule, dict):
        return "a rule must be an object"
    op = rule.get("op")
    if op not in OPS:
        return f"unknown check '{op}'"
    field = rule.get("field")
    if field is not None and (not isinstance(field, str) or len(field) > 200):
        return "the field must be text (\"text\" or a JSON field name)"
    if op in NO_VALUE_OPS:
        return None
    value = rule.get("value")
    if value is None or not _as_text(value).strip():
        return "needs a value to compare with"
    if op in NUMERIC_OPS and _as_number(value) is None:
        return f"'{OPS[op]}' needs a number to compare with"
    return None


def rule_summary(rule: dict | None) -> str:
    """Short human label for a rule, e.g. `contains "urgent"`, `amount > 10000`."""
    if not isinstance(rule, dict) or rule.get("op") not in OPS:
        return ""
    field = (rule.get("field") or "text").strip()
    subject = "" if field in ("", "text") else f"{field} "
    op = rule["op"]
    if op in NO_VALUE_OPS:
        return f"{subject}{OPS[op]}".strip()
    value = _as_text(rule.get("value"))
    shown = value if op in NUMERIC_OPS else f'"{value}"'
    return f"{subject}{OPS[op]} {shown}".strip()
