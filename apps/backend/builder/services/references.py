"""Checks against the database: do the agents, tools and knowledge bases a
definition points at exist, may this user use them, and — for preflight —
has this user connected every server their tools live on?

Two levels:

* **Save** (``check_connection=False``): the definition is sound for anyone in
  the tenant — each referenced agent is in the tenant (and standalone or
  owned by this workflow), each tool exists and its server is visible to the
  saving user, each knowledge base is in the tenant.
* **Preflight** (``check_connection=True``): everything above, plus the user
  who is about to run it has their own connection for every server involved.
  A workflow is shared in the tenant but always runs with the runner's own
  connections, so this is per user.

Problems are ``GraphProblem``s (same shape as structural ones), deduplicated
so one missing connection used by three steps reads as one problem.
"""
from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from knowledge.models import KnowledgeBase
from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth
from vendor.services.mcp_service.crud import is_server_visible_to_user

from builder.agents.config import AgentConfig, merge_config
from builder.graph.schema import WorkflowConfig, WorkflowNode, parse_tool_id
from builder.graph.schema import WorkflowEdge
from builder.graph.validation import GraphProblem, validate_graph
from builder.models import BuilderAgent


def _dedupe(problems: list[GraphProblem]) -> list[GraphProblem]:
    seen: set[tuple[str, str]] = set()
    out: list[GraphProblem] = []
    for p in problems:
        key = (p.code, p.message)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def config_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
        for err in exc.errors(include_url=False)
    ][:10]


async def tool_problems(
    db: AsyncSession,
    user: CurrentUser,
    tool_ids: list[str],
    *,
    node_id: str | None = None,
    check_connection: bool,
) -> list[GraphProblem]:
    refs = [(tid, parse_tool_id(tid)) for tid in dict.fromkeys(tool_ids)]
    problems = [
        GraphProblem("tool_invalid", f"'{tid}' is not a valid tool reference.", node_id)
        for tid, parsed in refs if parsed is None
    ]
    parsed_refs = [(tid, p) for tid, p in refs if p is not None]
    if not parsed_refs:
        return problems

    server_ids = {sid for _, (sid, _) in parsed_refs}
    servers = {
        s.id: s
        for s in (await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_(server_ids)))).scalars()
    }
    tool_names = {
        (row.mcp_server_id, row.name)
        for row in (
            await db.execute(select(MCPTool.mcp_server_id, MCPTool.name).where(MCPTool.mcp_server_id.in_(server_ids)))
        ).all()
    }
    visible: dict[str, bool] = {}
    connected: dict[str, bool] = {}
    for tid, (server_id, tool_name) in parsed_refs:
        server = servers.get(server_id)
        if server_id not in visible:
            visible[server_id] = server is not None and await is_server_visible_to_user(db, user=user, server=server)
        if not visible[server_id]:
            problems.append(GraphProblem("server_unavailable", "A tool's MCP server no longer exists or isn't available to you.", node_id))
            continue
        if (server_id, tool_name) not in tool_names:
            problems.append(GraphProblem("tool_unavailable", f"{server.name} no longer has a tool named '{tool_name}'.", node_id))
            continue
        if check_connection:
            if server_id not in connected:
                connected[server_id] = await mcp_auth.has_user_credential(db, server_id=server_id, user_id=user.id)
            if not connected[server_id]:
                problems.append(GraphProblem(
                    "not_connected", f"Connect your {server.name} account first.", node_id, server_id=server_id,
                ))
    return problems


async def knowledge_problems(
    db: AsyncSession, tenant_id: str, kb_ids: list[str], *, node_id: str | None = None
) -> list[GraphProblem]:
    ids = list(dict.fromkeys(kb_ids))
    if not ids:
        return []
    found = set(
        (await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.id.in_(ids), KnowledgeBase.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    return [
        GraphProblem("knowledge_base_missing", "A knowledge base this uses was deleted.", node_id)
        for kb in ids if kb not in found
    ]


async def agent_config_problems(
    db: AsyncSession,
    user: CurrentUser,
    config: AgentConfig,
    *,
    node_id: str | None = None,
    check_connection: bool,
) -> list[GraphProblem]:
    problems = await tool_problems(db, user, config.tool_ids, node_id=node_id, check_connection=check_connection)
    problems += await knowledge_problems(db, user.tenant_id, config.knowledge_base_ids, node_id=node_id)
    return _dedupe(problems)


async def workflow_reference_problems(
    db: AsyncSession,
    user: CurrentUser,
    *,
    workflow_id: str | None,
    nodes: list[WorkflowNode],
    config: WorkflowConfig,
    check_connection: bool,
) -> list[GraphProblem]:
    problems: list[GraphProblem] = []
    agent_ids = {n.agent_id for n in nodes if n.type == "agent" and n.agent_id}
    agents = {
        a.id: a
        for a in (
            await db.execute(
                select(BuilderAgent).where(BuilderAgent.id.in_(agent_ids), BuilderAgent.tenant_id == user.tenant_id)
            )
        ).scalars()
    } if agent_ids else {}

    for n in nodes:
        if n.type == "agent" and n.draft_agent is not None:
            # A draft (new, or replacing the step's saved agent) is what will be saved.
            try:
                merged = AgentConfig.model_validate(merge_config(n.draft_agent.config, n.config_overrides))
            except ValidationError as exc:
                problems.append(GraphProblem("agent_overrides", "This step's new agent has invalid settings: " + "; ".join(config_errors(exc)), n.id))
                continue
            problems += await agent_config_problems(db, user, merged, node_id=n.id, check_connection=check_connection)
        elif n.type == "agent" and n.agent_id:
            agent = agents.get(n.agent_id)
            if agent is None:
                problems.append(GraphProblem("agent_not_found", "The agent this step uses was deleted.", n.id))
                continue
            if agent.workflow_id is not None and agent.workflow_id != workflow_id:
                problems.append(GraphProblem(
                    "agent_of_other_workflow",
                    f'Agent "{agent.name}" belongs to another workflow. Pick a standalone agent or create a new one.',
                    n.id,
                ))
                continue
            try:
                merged = AgentConfig.model_validate(merge_config(agent.config, n.config_overrides))
            except ValidationError as exc:
                problems.append(GraphProblem("agent_overrides", "This step's agent settings are invalid: " + "; ".join(config_errors(exc)), n.id))
                continue
            problems += await agent_config_problems(db, user, merged, node_id=n.id, check_connection=check_connection)
        elif n.type == "tool" and n.tool_id and parse_tool_id(n.tool_id):
            problems += await tool_problems(db, user, [n.tool_id], node_id=n.id, check_connection=check_connection)

    problems += await knowledge_problems(db, user.tenant_id, config.default_knowledge_base_ids)
    return _dedupe(problems)


async def check_workflow(
    db: AsyncSession,
    user: CurrentUser,
    *,
    workflow_id: str | None,
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
    config: WorkflowConfig,
    check_connection: bool,
) -> list[GraphProblem]:
    """Structure + references (+ this user's connections, for preflight)."""
    problems = validate_graph(nodes, edges)
    problems += await workflow_reference_problems(
        db, user, workflow_id=workflow_id, nodes=nodes, config=config, check_connection=check_connection
    )
    return problems


__all__ = [
    "config_errors",
    "tool_problems",
    "knowledge_problems",
    "agent_config_problems",
    "workflow_reference_problems",
    "check_workflow",
]
