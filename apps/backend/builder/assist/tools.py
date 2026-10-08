"""Find the right tools for a step: hybrid search first, then the model picks.

The hybrid search (``user.services.catalog_engine.get_relevant_tools_semantic``:
vectors + BM25 + reranker over the tools this user may use) narrows the
whole catalog to a short candidate list for the step's own need; the model
then chooses only from that list, and anything it names that isn't on it is
ignored. A large catalog therefore never reaches the prompt, and a tool the
user isn't allowed to use is never suggested.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from user.services.catalog_engine import get_relevant_tools_semantic, get_user_connected_server_ids

from builder.assist.llm import Usage, ask_json
from builder.assist.prompts import pick_tools_prompt
from builder.graph.schema import make_tool_id
from builder.services.tool_runtime import classify_tool


@dataclass
class Candidate:
    tool_id: str
    server_id: str
    server_name: str
    tool_name: str
    description: str
    risk: str
    connected: bool

    def line(self) -> str:
        return f"{self.tool_id} | {self.server_name}.{self.tool_name}: {self.description} [{self.risk}]"

    def as_dict(self) -> dict:
        return {
            "tool_id": self.tool_id, "server_id": self.server_id, "server_name": self.server_name,
            "tool_name": self.tool_name, "description": self.description, "risk": self.risk, "connected": self.connected,
        }


async def search_tools(
    db: AsyncSession, user: CurrentUser, query: str, *, top_k_servers: int = 5, top_k_tools: int = 8
) -> list[Candidate]:
    if not query.strip():
        return []
    matches = await get_relevant_tools_semantic(db, user=user, query=query, top_k_servers=top_k_servers, top_k_tools=top_k_tools)
    connected = await get_user_connected_server_ids(db, server_ids=list({s.id for s, _, _ in matches}), user_id=user.id)
    return [
        Candidate(
            tool_id=make_tool_id(server.id, tool.name), server_id=server.id, server_name=server.name,
            tool_name=tool.name, description=(tool.description or "")[:300],
            risk=classify_tool(tool.name, tool.annotations).risk, connected=server.id in connected,
        )
        for server, tool, _score in matches
    ]


async def pick_tool(db: AsyncSession, user: CurrentUser, need: str, context: str, usage: Usage) -> Candidate | None:
    """The one tool that performs a tool step's action, or None."""
    candidates = await search_tools(db, user, need)
    if not candidates:
        return None
    answer = await ask_json(pick_tools_prompt(f"{need}\n\n{context}".strip(), [c.line() for c in candidates], single=True), usage)
    chosen = answer.get("tool_id")
    return next((c for c in candidates if c.tool_id == chosen), None)


async def pick_agent_tools(db: AsyncSession, user: CurrentUser, step: str, needs: str, usage: Usage) -> list[Candidate]:
    """The tools an agent needs. Nothing to search for -> no tools."""
    if not needs.strip():
        return []
    candidates = await search_tools(db, user, needs, top_k_tools=10)
    if not candidates:
        return []
    answer = await ask_json(pick_tools_prompt(step, [c.line() for c in candidates], single=False), usage)
    chosen = answer.get("tool_ids") if isinstance(answer.get("tool_ids"), list) else []
    by_id = {c.tool_id: c for c in candidates}
    return [by_id[t] for t in dict.fromkeys(chosen) if t in by_id][:8]


__all__ = ["Candidate", "search_tools", "pick_tool", "pick_agent_tools"]
