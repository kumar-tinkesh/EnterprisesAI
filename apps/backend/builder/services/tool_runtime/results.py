"""Turn an MCP ``CallToolResult`` into one plain, size-capped shape.

``text`` is what an agent (and the UI) reads: every text block joined, plus a
short placeholder for each non-text block. ``content`` keeps the blocks' kinds
and metadata; binary payloads (images, audio, blob resources) are summarised,
never passed through, so one screenshot can't blow up a run's state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mcp import types


@dataclass
class ToolOutput:
    is_error: bool
    text: str
    structured: Any = None
    content: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


def _cap(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n… [truncated {len(text) - limit} characters]", True


def _block(block: Any) -> tuple[dict[str, Any], str]:
    """(metadata dict, text contribution) for one content block."""
    if isinstance(block, types.TextContent):
        return {"type": "text"}, block.text
    if isinstance(block, types.ImageContent):
        size = len(block.data or "") * 3 // 4
        return {"type": "image", "mime_type": block.mime_type, "bytes": size}, f"[image {block.mime_type}, {size} bytes]"
    if isinstance(block, types.AudioContent):
        size = len(block.data or "") * 3 // 4
        return {"type": "audio", "mime_type": block.mime_type, "bytes": size}, f"[audio {block.mime_type}, {size} bytes]"
    if isinstance(block, types.EmbeddedResource):
        res = block.resource
        uri = str(getattr(res, "uri", ""))
        if isinstance(res, types.TextResourceContents):
            return {"type": "resource", "uri": uri, "mime_type": res.mime_type}, res.text
        return {"type": "resource", "uri": uri, "mime_type": getattr(res, "mime_type", None)}, f"[binary resource {uri}]"
    if isinstance(block, types.ResourceLink):
        uri = str(block.uri)
        return {"type": "resource_link", "uri": uri, "name": block.name}, f"[resource link {block.name}: {uri}]"
    kind = getattr(block, "type", type(block).__name__)
    return {"type": str(kind)}, f"[{kind} content]"


def normalize_result(result: types.CallToolResult, *, max_chars: int) -> ToolOutput:
    content: list[dict[str, Any]] = []
    parts: list[str] = []
    for block in result.content or []:
        meta, text = _block(block)
        content.append(meta)
        if text:
            parts.append(text)

    structured = result.structured_content
    if not parts and structured is not None:
        # Structured-only results still need something an agent can read.
        parts.append(json.dumps(structured, ensure_ascii=False, default=str))

    text, truncated = _cap("\n\n".join(parts), max_chars)
    if structured is not None:
        encoded = json.dumps(structured, ensure_ascii=False, default=str)
        if len(encoded) > max_chars:
            structured, truncated = None, True
    return ToolOutput(
        is_error=bool(result.is_error),
        text=text,
        structured=structured,
        content=content,
        truncated=truncated,
    )


__all__ = ["ToolOutput", "normalize_result"]
