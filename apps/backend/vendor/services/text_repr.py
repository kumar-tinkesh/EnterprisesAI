"""Pure text-representation builders for MCP servers/tools.

Shared by both the vendor write-path (``vendor.services.embedding``, which
embeds this text when a server/tool is registered or re-verified) and the
user read-path (``user.services.catalog_engine``, which needs the *exact
same* text to hand to BM25/the reranker so lexical and vector ranking agree
with what was embedded). These are pure, side-effect-free functions — no DB
access, no mutation — which is why ``user`` importing this one vendor
module is a narrow, documented exception to the "user never imports
vendor.services" rule (see the repo's import-linter contracts).
"""
from __future__ import annotations

from vendor.models import MCPTool, VendorMCPServer


def server_text(server: VendorMCPServer) -> str:
    return f"{server.name}. {server.description}".strip(". ")


def tool_text(tool: MCPTool) -> str:
    properties = ""
    if isinstance(tool.input_schema, dict):
        properties = " ".join((tool.input_schema.get("properties") or {}).keys())
    return f"{tool.name}. {tool.description} {properties}".strip(". ")


__all__ = ["server_text", "tool_text"]
