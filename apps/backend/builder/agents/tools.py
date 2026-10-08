"""The tools an agent may call, as LLM function definitions.

* Each ``mcp:<server_id>:<tool_name>`` in the agent's config becomes one
  function, named ``<server>__<tool>`` (unique, provider-safe), with the
  tool's own JSON Schema as its parameters.
* An agent with knowledge bases also gets ``search_knowledge`` — hybrid
  retrieval over those knowledge bases (``knowledge.services.retrieval``).

Tools that are no longer available (server removed, tool gone) are left out
rather than failing the run; preflight already reported them before it started.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vendor.models import MCPTool, VendorMCPServer

from builder.graph.schema import parse_tool_id

KNOWLEDGE_TOOL = "search_knowledge"
_MAX_NAME = 64


@dataclass(frozen=True)
class AgentTool:
    function_name: str
    server_id: str
    server_name: str
    tool_name: str
    description: str
    input_schema: dict
    annotations: dict | None


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_").lower() or "tool"


def function_definitions(tools: list[AgentTool], *, with_knowledge: bool) -> list[dict]:
    """[{name, description, parameters}] in the order the model sees them."""
    defs = [
        {
            "name": t.function_name,
            "description": f"[{t.server_name}] {t.description}".strip(),
            "parameters": t.input_schema or {"type": "object", "properties": {}},
        }
        for t in tools
    ]
    if with_knowledge:
        defs.append({
            "name": KNOWLEDGE_TOOL,
            "description": "Search this agent's knowledge base (company documents) and return the most relevant passages with their source.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for, in plain words"}},
                "required": ["query"],
            },
        })
    return defs


async def resolve_agent_tools(db: AsyncSession, tool_ids: list[str]) -> list[AgentTool]:
    refs = [p for p in (parse_tool_id(t) for t in tool_ids) if p]
    if not refs:
        return []
    server_ids = {sid for sid, _ in refs}
    servers = {s.id: s for s in (await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_(server_ids)))).scalars()}
    tools = {
        (t.mcp_server_id, t.name): t
        for t in (await db.execute(select(MCPTool).where(MCPTool.mcp_server_id.in_(server_ids)))).scalars()
    }
    out: list[AgentTool] = []
    taken: set[str] = {KNOWLEDGE_TOOL}
    for server_id, tool_name in refs:
        server, tool = servers.get(server_id), tools.get((server_id, tool_name))
        if server is None or tool is None:
            continue
        base = f"{_slug(server.name)}__{_slug(tool_name)}"[:_MAX_NAME]
        name, n = base, 2
        while name in taken:
            suffix = f"_{n}"
            name, n = base[: _MAX_NAME - len(suffix)] + suffix, n + 1
        taken.add(name)
        out.append(AgentTool(
            function_name=name,
            server_id=server_id,
            server_name=server.name,
            tool_name=tool_name,
            description=tool.description or "",
            input_schema=tool.input_schema or {"type": "object", "properties": {}},
            annotations=tool.annotations,
        ))
    return out


async def search_knowledge(db: AsyncSession, *, tenant_id: str, kb_ids: list[str], query: str, top_k: int = 6) -> str:
    """Retrieve across the agent's knowledge bases and format the passages for the model."""
    from knowledge.services.retrieval import retrieve

    hits: list[dict] = []
    for kb_id in kb_ids:
        hits.extend(await retrieve(db, knowledge_base_id=kb_id, tenant_id=tenant_id, query=query, k=top_k))
    hits.sort(key=lambda h: h["score"], reverse=True)
    if not hits:
        return "No relevant passages found in the knowledge base."
    return "\n\n".join(f"[{i}] (source: {h['filename']})\n{h['content']}" for i, h in enumerate(hits[:top_k], start=1))


__all__ = ["AgentTool", "KNOWLEDGE_TOOL", "function_definitions", "resolve_agent_tools", "search_knowledge"]
