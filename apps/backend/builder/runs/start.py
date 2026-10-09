"""Can this user run it right now? — the checks every run start goes through.

Shared by the run API (a person pressing Run) and the scheduler (a schedule
firing as its owner), so a scheduled run is held to exactly the same bar.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.agents.config import AgentConfig
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
from builder.graph.validation import GraphProblem
from builder.models import BuilderAgent, BuilderWorkflow
from builder.services.references import agent_config_problems, check_workflow


async def agent_run_problems(db: AsyncSession, user: CurrentUser, agent: BuilderAgent) -> list[GraphProblem]:
    return await agent_config_problems(db, user, AgentConfig.model_validate(agent.config or {}), check_connection=True)


async def workflow_run_problems(
    db: AsyncSession, user: CurrentUser, workflow: BuilderWorkflow, variables: dict
) -> list[GraphProblem]:
    nodes = [WorkflowNode.model_validate(n) for n in workflow.nodes or []]
    if not nodes:
        return [GraphProblem("empty", "This workflow has no steps yet.")]
    problems = await check_workflow(
        db, user, workflow_id=workflow.id, nodes=nodes,
        edges=[WorkflowEdge.model_validate(e) for e in workflow.edges or []],
        config=WorkflowConfig.model_validate(workflow.config or {}), check_connection=True,
    )
    for node in nodes:
        for var in node.variables or []:
            if var.required and variables.get(var.name) in (None, ""):
                problems.append(GraphProblem("missing_variable", f'Fill in "{var.label or var.name}" to run this workflow.', node.id))
    return problems


__all__ = ["agent_run_problems", "workflow_run_problems"]
