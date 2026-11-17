"""Agents as files, and what an agent needs before you can use it (mounted under ``/api/v1/builder``).

    GET  /agents/{agent_id}/requirements  servers its tools (and its team's tools) live on,
                                          and whether the caller has connected each
    GET  /agents/{agent_id}/export        the agent as a JSON file another workspace can import
    POST /agents/import                   create an agent from such a file

Every agent is shared in its tenant and each person runs it as themselves, so
the chat says up front which accounts are still to connect — with the same
checks a run makes.

A file names tools by server and tool name, not by id: ids differ between
workspaces. Import matches them against the servers the importer can see and
reports what it couldn't match instead of failing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

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
FILE_VERSION = 1


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


class AgentFile(BaseModel):
    format: str
    format_version: int
    agent: ExportedAgent
    tools: list[ExportedTool] = Field(default_factory=list, max_length=50)
    knowledge_bases: list[str] = Field(default_factory=list, max_length=10)
    sub_agents: list[str] = Field(default_factory=list, max_length=5)


class ImportOut(BaseModel):
    agent: AgentOut
    # What the file referred to that this workspace doesn't have (left out of the new agent).
    skipped: list[str]


# What a file never carries: references by id, which mean nothing in another workspace.
_BY_ID = ("tool_ids", "knowledge_base_ids", "sub_agent_ids")


@router.get("/agents/{agent_id}/export")
async def export_agent(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
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
    body = AgentFile(
        format=FILE_FORMAT,
        format_version=FILE_VERSION,
        agent=ExportedAgent(
            name=agent.name, role=agent.role, goal=agent.goal, instructions=agent.instructions or "",
            llm_provider=agent.llm_provider or "", llm_model=agent.llm_model or "",
            config={k: v for k, v in config.model_dump().items() if k not in _BY_ID},
        ),
        tools=[ExportedTool(server=servers[sid], tool=name) for sid, name in refs if sid in servers],
        knowledge_bases=list(kbs),
        sub_agents=list(subs),
    )
    slug = "".join(c if c.isalnum() else "-" for c in agent.name.lower()).strip("-") or "agent"
    return JSONResponse(
        content={**body.model_dump(), "exported_at": utcnow().isoformat()},
        headers={"Content-Disposition": f'attachment; filename="{slug}.agent.json"'},
    )


@router.post("/agents/import", response_model=ImportOut, status_code=201)
async def import_agent(payload: AgentFile, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    if payload.format != FILE_FORMAT:
        raise HTTPException(status_code=422, detail="This isn't an agent file exported from here.")
    if payload.format_version > FILE_VERSION:
        raise HTTPException(status_code=422, detail="This file comes from a newer version; update before importing it.")
    skipped: list[str] = []

    tool_ids: list[str] = []
    wanted = {t.server for t in payload.tools}
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
    for t in payload.tools:
        server = visible.get(t.server)
        if server is None:
            skipped.append(f"Tool {t.server}.{t.tool}: no server named \"{t.server}\" is available to you.")
        elif (server.id, t.tool) not in names:
            skipped.append(f"Tool {t.server}.{t.tool}: {t.server} has no tool by that name.")
        else:
            tool_ids.append(f"mcp:{server.id}:{t.tool}")

    kb_ids: list[str] = []
    for name in payload.knowledge_bases:
        kb = (await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.tenant_id == user.tenant_id, KnowledgeBase.name == name))).scalars().first()
        if kb:
            kb_ids.append(kb)
        else:
            skipped.append(f"Knowledge base \"{name}\": there is none by that name here.")

    sub_ids: list[str] = []
    for name in payload.sub_agents:
        sub = (
            await db.execute(select(BuilderAgent.id).where(
                BuilderAgent.tenant_id == user.tenant_id, BuilderAgent.workflow_id.is_(None), BuilderAgent.name == name,
            ))
        ).scalars().first()
        if sub:
            sub_ids.append(sub)
        else:
            skipped.append(f"Sub-agent \"{name}\": there is no agent by that name here.")

    raw = {k: v for k, v in payload.agent.config.items() if k not in _BY_ID}
    try:
        config = AgentConfig.model_validate({**raw, "tool_ids": tool_ids, "knowledge_base_ids": kb_ids, "sub_agent_ids": sub_ids})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="The file's settings aren't valid: " + "; ".join(config_errors(exc))) from exc

    a = payload.agent
    agent = BuilderAgent(
        tenant_id=user.tenant_id, owner_id=user.id, name=a.name.strip(), role=a.role.strip(), goal=a.goal.strip(),
        instructions=a.instructions.strip(), llm_provider=a.llm_provider.strip(), llm_model=a.llm_model.strip(),
        config=config.model_dump(),
    )
    db.add(agent)
    await record_version(db, "agent", agent, author_id=user.id, note="Imported")
    await db.commit()
    await db.refresh(agent)
    return ImportOut(agent=agent_out(agent, user), skipped=skipped)
