"""Agents as files, and what an agent needs before you can use it (mounted under ``/api/v1/builder``).

    GET  /agents/{agent_id}/requirements  servers its tools (and its team's tools) live on,
                                          and whether the caller has connected each
    GET  /agents/{agent_id}/export        the agent as a JSON file another workspace can import
                                          (?team=true: with the agents it hands work to, one file)
    POST /agents/import                   create the agent — or the whole team — from such a file

Every agent is shared in its tenant and each person runs it as themselves, so
the chat says up front which accounts are still to connect — with the same
checks a run makes.

A file names tools by server and tool name, not by id: ids differ between
workspaces. Import matches them against the servers the importer can see and
reports what it couldn't match instead of failing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db
from src.models.tenant import uuid_str

from knowledge.models import KnowledgeBase
from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.mcp_service.crud import is_server_visible_to_user

from builder.agents.config import AgentConfig
from builder.api.v1.agents import agent_out, get_agent
from builder.api.v1.definitions import AgentOut
from builder.api.v1.deps import get_end_user
from builder.graph.schema import parse_tool_id
from builder.models import BuilderAgent
from builder.runs.db import utcnow
from builder.services.references import config_errors
from builder.versions.service import record_version

router = APIRouter()

FILE_FORMAT = "enterprisesai.agent"
FILE_VERSION = 2  # 2 added team files (``agents``); 1 files still import


# ── what it needs ───────────────────────────────────────────────────────────


class Requirement(BaseModel):
    server_id: str
    name: str
    connected: bool
    tools: list[str]


class RequirementsOut(BaseModel):
    requirements: list[Requirement]
    ready: bool


async def _requirements(db: AsyncSession, user: CurrentUser, configs: list[AgentConfig]) -> list[Requirement]:
    tools_by_server: dict[str, list[str]] = {}
    for config in configs:
        for tid in config.tool_ids:
            parsed = parse_tool_id(tid)
            if parsed:
                tools_by_server.setdefault(parsed[0], []).append(parsed[1])
    if not tools_by_server:
        return []
    servers = {
        s.id: s for s in (await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_(tools_by_server)))).scalars()
    }
    out = []
    for sid, tools in tools_by_server.items():
        server = servers.get(sid)
        out.append(Requirement(
            server_id=sid,
            name=server.name if server else "A removed server",
            connected=bool(server) and await mcp_auth.has_user_credential(db, server_id=sid, user_id=user.id),
            tools=list(dict.fromkeys(tools)),
        ))
    return out


@router.get("/agents/{agent_id}/requirements", response_model=RequirementsOut)
async def agent_requirements(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    config = AgentConfig.model_validate(agent.config or {})
    subs = [
        AgentConfig.model_validate(a.config or {})
        for a in (
            await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(config.sub_agent_ids), BuilderAgent.tenant_id == user.tenant_id))
        ).scalars()
    ] if config.sub_agent_ids else []
    requirements = await _requirements(db, user, [config, *subs])
    return RequirementsOut(requirements=requirements, ready=all(r.connected for r in requirements))


# ── export / import ─────────────────────────────────────────────────────────

# The most agents one file may carry: a lead and its team (an agent has at most five sub-agents).
MAX_TEAM = 10


class ExportedTool(BaseModel):
    server: str = Field(max_length=255)
    tool: str = Field(max_length=255)


class ExportedAgent(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=20_000)
    llm_provider: str = Field(default="", max_length=50)
    llm_model: str = Field(default="", max_length=100)
    config: dict = Field(default_factory=dict)


class AgentEntry(BaseModel):
    """One agent in a file, with what it refers to by name."""

    agent: ExportedAgent
    tools: list[ExportedTool] = Field(default_factory=list, max_length=50)
    knowledge_bases: list[str] = Field(default_factory=list, max_length=10)
    # Agents it hands work to: another agent in the same file, or one already in the workspace.
    sub_agents: list[str] = Field(default_factory=list, max_length=5)


class AgentFile(BaseModel):
    """Version 1 is one agent: ``agent`` with its references beside it.
    Version 2 is a team: ``agents``, each with its own references. Sub-agents
    named from the same file are created with it, so a whole team imports
    at once and the order inside the file doesn't matter."""

    format: str
    format_version: int
    agent: ExportedAgent | None = None
    tools: list[ExportedTool] = Field(default_factory=list, max_length=50)
    knowledge_bases: list[str] = Field(default_factory=list, max_length=10)
    sub_agents: list[str] = Field(default_factory=list, max_length=5)
    agents: list[AgentEntry] = Field(default_factory=list, max_length=MAX_TEAM)

    def entries(self) -> list[AgentEntry]:
        if self.agents:
            return self.agents
        if self.agent:
            return [AgentEntry(agent=self.agent, tools=self.tools, knowledge_bases=self.knowledge_bases, sub_agents=self.sub_agents)]
        return []


class ImportOut(BaseModel):
    # The agent to open: for a team, its lead (the one no other agent in the file hands work to).
    agent: AgentOut
    # Every agent created, sub-agents before the agents that use them.
    agents: list[AgentOut]
    # What the file referred to that this workspace doesn't have (left out of the new agents).
    skipped: list[str]


# What a file never carries: references by id, which mean nothing in another workspace.
_BY_ID = ("tool_ids", "knowledge_base_ids", "sub_agent_ids")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "agent"


async def _entry(db: AsyncSession, user: CurrentUser, agent: BuilderAgent) -> AgentEntry:
    """One saved agent as a file entry: its references by name instead of id."""
    config = AgentConfig.model_validate(agent.config or {})
    refs = [p for p in (parse_tool_id(t) for t in config.tool_ids) if p]
    servers = {
        s.id: s.name
        for s in (await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_({sid for sid, _ in refs})))).scalars()
    } if refs else {}
    kbs = (
        await db.execute(select(KnowledgeBase.name).where(KnowledgeBase.id.in_(config.knowledge_base_ids), KnowledgeBase.tenant_id == user.tenant_id))
    ).scalars().all() if config.knowledge_base_ids else []
    subs = (
        await db.execute(select(BuilderAgent.name).where(BuilderAgent.id.in_(config.sub_agent_ids), BuilderAgent.tenant_id == user.tenant_id))
    ).scalars().all() if config.sub_agent_ids else []
    return AgentEntry(
        agent=ExportedAgent(
            name=agent.name, role=agent.role, goal=agent.goal, instructions=agent.instructions or "",
            llm_provider=agent.llm_provider or "", llm_model=agent.llm_model or "",
            config={k: v for k, v in config.model_dump().items() if k not in _BY_ID},
        ),
        tools=[ExportedTool(server=servers[sid], tool=name) for sid, name in refs if sid in servers],
        knowledge_bases=list(kbs),
        sub_agents=list(subs),
    )


@router.get("/agents/{agent_id}/export")
async def export_agent(
    agent_id: str,
    team: bool = Query(default=False, description="Also put the agents it hands work to in the file (a version 2 team file)."),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    lead = await _entry(db, user, agent)
    members: list[BuilderAgent] = []
    if team:
        ids = AgentConfig.model_validate(agent.config or {}).sub_agent_ids
        rows = {
            a.id: a
            for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(ids), BuilderAgent.tenant_id == user.tenant_id))).scalars()
        } if ids else {}
        members = [rows[i] for i in ids if i in rows and i != agent.id]
    if members:
        entries = [await _entry(db, user, m) for m in members] + [lead]
        body = {"format": FILE_FORMAT, "format_version": 2, "agents": [e.model_dump() for e in entries]}
        filename = f"{_slug(agent.name)}-team.agent.json"
    else:
        # A single agent stays a version 1 file, so older installs can still import it.
        body = {"format": FILE_FORMAT, "format_version": 1, **lead.model_dump()}
        filename = f"{_slug(agent.name)}.agent.json"
    return JSONResponse(
        content={**body, "exported_at": utcnow().isoformat()},
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _team_order(entries: list[AgentEntry], in_file: dict[str, int]) -> list[int]:
    """Entry indexes with every sub-agent from the file before the agent that uses it."""
    order: list[int] = []
    state: dict[int, str] = {}  # "busy" while its sub-agents are being placed, then "done"

    def visit(i: int, path: list[str]) -> None:
        if state.get(i) == "done":
            return
        name = entries[i].agent.name.strip()
        if state.get(i) == "busy":
            raise HTTPException(status_code=422, detail="The agents in this file hand work to each other in a loop: " + " → ".join([*path, name]) + ".")
        state[i] = "busy"
        for sub in entries[i].sub_agents:
            j = in_file.get(sub.strip().lower())
            if j is not None:
                visit(j, [*path, name])
        state[i] = "done"
        order.append(i)

    for i in range(len(entries)):
        visit(i, [])
    return order


async def _match_tools(db: AsyncSession, user: CurrentUser, tools: list[ExportedTool]) -> tuple[list[str], list[str]]:
    skipped: list[str] = []
    tool_ids: list[str] = []
    wanted = {t.server for t in tools}
    candidates = list((await db.execute(select(VendorMCPServer).where(VendorMCPServer.name.in_(wanted)))).scalars()) if wanted else []
    visible: dict[str, VendorMCPServer] = {}
    for s in candidates:
        if s.name not in visible and await is_server_visible_to_user(db, user=user, server=s):
            visible[s.name] = s
    names = {
        (row.mcp_server_id, row.name)
        for row in (
            await db.execute(select(MCPTool.mcp_server_id, MCPTool.name).where(MCPTool.mcp_server_id.in_([s.id for s in visible.values()])))
        ).all()
    } if visible else set()
    for t in tools:
        server = visible.get(t.server)
        if server is None:
            skipped.append(f"Tool {t.server}.{t.tool}: no server named \"{t.server}\" is available to you.")
        elif (server.id, t.tool) not in names:
            skipped.append(f"Tool {t.server}.{t.tool}: {t.server} has no tool by that name.")
        else:
            tool_ids.append(f"mcp:{server.id}:{t.tool}")
    return tool_ids, skipped


@router.post("/agents/import", response_model=ImportOut, status_code=201)
async def import_agent(payload: AgentFile, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    if payload.format != FILE_FORMAT:
        raise HTTPException(status_code=422, detail="This isn't an agent file exported from here.")
    if payload.format_version > FILE_VERSION:
        raise HTTPException(status_code=422, detail="This file comes from a newer version; update before importing it.")
    entries = payload.entries()
    if not entries:
        raise HTTPException(status_code=422, detail="This file has no agent in it.")
    names = [e.agent.name.strip() for e in entries]
    in_file: dict[str, int] = {}
    for i, name in enumerate(names):
        if name.lower() in in_file:
            raise HTTPException(status_code=422, detail=f'Two agents in this file are called "{name}"; each needs its own name.')
        in_file[name.lower()] = i
    order = _team_order(entries, in_file)
    ids = [uuid_str() for _ in entries]
    team = len(entries) > 1

    # Everything is worked out and checked before anything is saved: a team arrives whole or not at all.
    skipped: list[str] = []
    agents: dict[int, BuilderAgent] = {}
    for i in order:
        e, a = entries[i], entries[i].agent
        mine: list[str] = []
        tool_ids, missing = await _match_tools(db, user, e.tools)
        mine += missing

        kb_ids: list[str] = []
        for name in e.knowledge_bases:
            kb = (await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.tenant_id == user.tenant_id, KnowledgeBase.name == name))).scalars().first()
            if kb:
                kb_ids.append(kb)
            else:
                mine.append(f"Knowledge base \"{name}\": there is none by that name here.")

        sub_ids: list[str] = []
        for name in e.sub_agents:
            j = in_file.get(name.strip().lower())
            if j is not None:
                sub_ids.append(ids[j])  # a teammate from this file
                continue
            sub = (
                await db.execute(select(BuilderAgent.id).where(
                    BuilderAgent.tenant_id == user.tenant_id, BuilderAgent.workflow_id.is_(None), BuilderAgent.name == name,
                ))
            ).scalars().first()
            if sub:
                sub_ids.append(sub)
            else:
                mine.append(f"Sub-agent \"{name}\": there is no agent by that name here or in the file.")

        raw = {k: v for k, v in a.config.items() if k not in _BY_ID}
        try:
            config = AgentConfig.model_validate({**raw, "tool_ids": tool_ids, "knowledge_base_ids": kb_ids, "sub_agent_ids": sub_ids})
        except ValidationError as exc:
            where = f' of "{names[i]}"' if team else ""
            raise HTTPException(status_code=422, detail=f"The settings{where} in the file aren't valid: " + "; ".join(config_errors(exc))) from exc
        skipped += [f"{names[i]} — {s}" for s in mine] if team else mine
        agents[i] = BuilderAgent(
            id=ids[i], tenant_id=user.tenant_id, owner_id=user.id, name=names[i], role=a.role.strip(), goal=a.goal.strip(),
            instructions=a.instructions.strip(), llm_provider=a.llm_provider.strip(), llm_model=a.llm_model.strip(),
            config=config.model_dump(),
        )

    for i in order:
        db.add(agents[i])
        await record_version(db, "agent", agents[i], author_id=user.id, note="Imported")
    await db.commit()
    for agent in agents.values():
        await db.refresh(agent)

    used = {in_file[s.strip().lower()] for e in entries for s in e.sub_agents if s.strip().lower() in in_file}
    leads = [i for i in order if i not in used]
    lead = leads[-1] if leads else order[-1]
    return ImportOut(agent=agent_out(agents[lead], user), agents=[agent_out(agents[i], user) for i in order], skipped=skipped)
