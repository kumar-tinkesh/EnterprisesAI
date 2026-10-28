"""Ready-made workflows, created in one click (``builder.api.v1.templates``).

Each template is ``{key, name, summary, build}``; ``build()`` returns a
``WorkflowCreate`` body whose agent steps are ``draft_agent``s, minted as the
new workflow's own agents on save. Their tools are ``tool_needs``, so a
template never depends on server ids and is picked up as systems get connected.
"""
from __future__ import annotations

from builder.templates.job_finder import TEMPLATE as JOB_FINDER
from builder.templates.lead_research import TEMPLATE as LEAD_RESEARCH

TEMPLATES: dict[str, dict] = {t["key"]: t for t in (LEAD_RESEARCH, JOB_FINDER)}


def template_needs(body: dict) -> list[dict]:
    """Every system the template's steps use, once each (required if any step requires it)."""
    out: dict[str, dict] = {}
    for node in body["nodes"]:
        for need in ((node.get("draft_agent") or {}).get("config") or {}).get("tool_needs") or []:
            seen = out.get(need["system"])
            if seen is None:
                out[need["system"]] = {**need, "tools": list(need.get("tools") or [])}
            else:
                seen["required"] = seen["required"] or need.get("required", False)
                seen["tools"] += [t for t in need.get("tools") or [] if t not in seen["tools"]]
    return list(out.values())


__all__ = ["TEMPLATES", "template_needs"]
