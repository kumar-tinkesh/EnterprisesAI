"""An agent's ``tool_needs`` -> the tools it gets, for the person running it.

    states = await resolve_needs(db, user, config.tool_needs)

A need names a system by where its MCP server comes from (a repo slug or a
URL), never by server id, so a template can be made before the server exists:
an admin adds it under any name, the person connects it, and the next run
picks its tools up. Nothing is written back to the agent.

Each need ends up in one state:

  ready          a matching server is verified, the person connected it, and it has tools
  not_connected  verified, but this person hasn't connected it yet (they can, in place)
  not_verified   added by the admin, but not connected/tested yet, so it has no tools
  missing        no server the person can see comes from there

Of several matching servers the most usable one wins (ready > not_connected >
not_verified).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.mcp_service.crud import is_server_visible_to_user

from builder.agents.config import ToolNeed
from builder.graph.schema import make_tool_id
from builder.graph.validation import GraphProblem

NeedStatus = Literal["ready", "not_connected", "not_verified", "missing"]
_RANK: dict[str, int] = {"ready": 0, "not_connected": 1, "not_verified": 2, "missing": 3}
# Without a listed tool on the server, all its tools — up to this many.
MAX_FALLBACK_TOOLS = 15


@dataclass
class NeedState:
    need: ToolNeed
    status: NeedStatus
    server_id: str | None = None
    server_name: str | None = None
    tool_names: list[str] = field(default_factory=list)

    @property
    def tool_ids(self) -> list[str]:
        return [make_tool_id(self.server_id, t) for t in self.tool_names] if self.status == "ready" and self.server_id else []

    def as_dict(self) -> dict:
        return {
            "system": self.need.system,
            "required": self.need.required,
            "match": self.need.match,
            "status": self.status,
            "server_id": self.server_id,
            "server_name": self.server_name,
            "tools": self.tool_names if self.status == "ready" else [],
        }


def _norm(text: str | None) -> str:
    """"https://github.com/Owner/Repo.git/" -> "github.com/owner/repo"."""
    t = (text or "").strip().lower()
    t = re.sub(r"^[a-z+]+://", "", t)
    t = re.sub(r"^git@([^:]+):", r"\1/", t)
    t = re.sub(r"\.git(?=/|$)", "", t)
    return t.rstrip("/")


def server_matches(server: VendorMCPServer, need: ToolNeed) -> bool:
    places = [_norm(p) for p in (server.source_repo_url, server.source_repo, server.server_url, server.endpoint) if p]
    return any(_norm(m) and _norm(m) in p for m in need.match for p in places)


def pick_tools(need: ToolNeed, available: list[str]) -> list[str]:
    """The need's tools as the server names them: the same name, or the name
    under a prefix ("jobspy_search_jobs" for "search_jobs"). None of them
    there (renamed upstream, or no list) -> all the server's tools."""
    picked: list[str] = []
    for want in need.tools:
        w = want.lower()
        hit = next((a for a in available if a.lower() == w), None) or next(
            (a for a in available if a.lower().endswith("_" + w) or a.lower().endswith("-" + w)), None
        )
        if hit and hit not in picked:
            picked.append(hit)
    return picked or available[:MAX_FALLBACK_TOOLS]


async def resolve_needs(
    db: AsyncSession, user: CurrentUser, needs: list[ToolNeed], *, user_for: Callable[[str], CurrentUser] | None = None,
) -> list[NeedState]:
    """``user_for(server_id)``: whose account a server is used with, when that
    isn't always ``user`` (a mixed share link: some servers are the publisher's)."""
    if not needs:
        return []
    owner = user_for or (lambda _sid: user)
    servers = list((await db.execute(select(VendorMCPServer))).scalars())
    tools_of: dict[str, list[str]] = {}
    visible: dict[str, bool] = {}
    connected: dict[str, bool] = {}
    states: list[NeedState] = []
    for need in needs:
        best = NeedState(need, "missing")
        for server in servers:
            if not server_matches(server, need):
                continue
            if server.id not in visible:
                visible[server.id] = await is_server_visible_to_user(db, user=owner(server.id), server=server)
            if not visible[server.id]:
                continue
            if server.id not in tools_of:
                tools_of[server.id] = list(
                    (await db.execute(select(MCPTool.name).where(MCPTool.mcp_server_id == server.id).order_by(MCPTool.name))).scalars()
                )
            if server.status != "VERIFIED" or not tools_of[server.id]:
                state = NeedState(need, "not_verified", server.id, server.name)
            else:
                if server.id not in connected:
                    connected[server.id] = await mcp_auth.has_user_credential(db, server_id=server.id, user_id=owner(server.id).id)
                state = (
                    NeedState(need, "ready", server.id, server.name, pick_tools(need, tools_of[server.id]))
                    if connected[server.id] else NeedState(need, "not_connected", server.id, server.name)
                )
            if _RANK[state.status] < _RANK[best.status]:
                best = state
        states.append(best)
    return states


def need_problems(states: list[NeedState], *, node_id: str | None = None) -> list[GraphProblem]:
    """What stops a step with these needs from running: a required system
    that isn't ready, or — when none is required — not one of them ready."""
    if not states:
        return []

    def problem(s: NeedState) -> GraphProblem:
        system = s.need.system
        if s.status == "not_connected":
            return GraphProblem("not_connected", f"Connect your {system} account first ({s.server_name}).", node_id, server_id=s.server_id)
        if s.status == "not_verified":
            return GraphProblem("need_not_verified", f"{system} ({s.server_name}) is added but not connected by your admin yet, so it has no tools.", node_id)
        return GraphProblem("need_missing", f"{system} isn't available: ask your admin to add its MCP server ({s.need.match[0]}).", node_id)

    required = [s for s in states if s.need.required and s.status != "ready"]
    if required:
        return [problem(s) for s in required]
    if any(s.status == "ready" for s in states):
        return []
    # Not one connected: offer the nearest (connectable ones first).
    nearest = sorted(states, key=lambda s: _RANK[s.status])
    first = problem(nearest[0])
    names = ", ".join(s.need.system for s in states)
    return [GraphProblem(first.code, f"Connect at least one of {names}. {first.message}", node_id, server_id=first.server_id)]


__all__ = ["NeedState", "MAX_FALLBACK_TOOLS", "need_problems", "pick_tools", "resolve_needs", "server_matches"]
