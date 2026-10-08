"""Is a tool safe to run without asking? Classify it as read, edit or delete.

Two signals, combined conservatively:

* The tool's name, split into words (``get_invoices``, ``sendMessage``,
  ``delete-row``) and checked for verbs — ported from the AI Marketplace's
  ``connectors/registry/classification.py`` (delete verbs win over edit verbs,
  which win over read verbs).
* The server's own MCP annotations (``read_only_hint`` / ``destructive_hint``),
  stored on ``MCPTool.annotations`` when the server was verified. These are
  hints from the server, so they can make a tool *less* trusted but only lift
  it to "read" when its name doesn't say "delete".

Anything that can't be shown to be read-only is "edit": an unknown tool must
ask before it runs, never the other way round.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Risk = Literal["read", "edit", "delete"]

_DELETE_VERBS = frozenset({"delete", "remove", "destroy", "purge", "void", "abort", "cancel", "drop", "erase", "revoke"})
_EDIT_VERBS = frozenset({
    "create", "update", "patch", "insert", "add", "send", "post", "upload", "write", "set",
    "modify", "move", "close", "merge", "sync", "edit", "rename", "save", "publish", "reply",
    "approve", "assign", "archive", "execute", "run", "invite", "transfer", "pay", "submit",
})
_READ_VERBS = frozenset({
    "get", "list", "search", "read", "find", "query", "fetch", "describe", "retrieve", "view",
    "scrape", "scraper", "export", "download", "extract", "crawl", "map", "research", "lookup",
    "discover", "count", "check", "show", "inspect", "summarize", "summarise", "whoami", "ping",
})


@dataclass(frozen=True)
class ToolRisk:
    risk: Risk
    # "name" | "annotation" | "default" — why it got this level (shown in the UI).
    reason: str

    @property
    def needs_confirmation(self) -> bool:
        return self.risk != "read"


def _name_words(tool_name: str) -> list[str]:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", tool_name or "")
    return [w for w in re.split(r"[^a-z0-9]+", camel_split.lower()) if w]


def _risk_from_name(tool_name: str) -> Risk | None:
    words = _name_words(tool_name)
    if any(w in _DELETE_VERBS for w in words):
        return "delete"
    if any(w in _EDIT_VERBS for w in words):
        return "edit"
    if any(w in _READ_VERBS for w in words):
        return "read"
    return None


def _hint(annotations: dict, snake: str, camel: str) -> bool | None:
    value = annotations.get(snake, annotations.get(camel))
    return value if isinstance(value, bool) else None


def classify_tool(tool_name: str, annotations: dict | None = None) -> ToolRisk:
    by_name = _risk_from_name(tool_name)
    hints = annotations if isinstance(annotations, dict) else {}
    read_only = _hint(hints, "read_only_hint", "readOnlyHint")
    destructive = _hint(hints, "destructive_hint", "destructiveHint")

    if by_name == "delete":
        return ToolRisk("delete", "name")
    # Per the MCP spec, destructive_hint only means something when the tool
    # is explicitly not read-only.
    if read_only is False and destructive is True:
        return ToolRisk("delete", "annotation")
    if read_only is True:
        return ToolRisk("read", "annotation")
    if by_name is not None:
        return ToolRisk(by_name, "name")
    return ToolRisk("edit", "default")


__all__ = ["Risk", "ToolRisk", "classify_tool"]
