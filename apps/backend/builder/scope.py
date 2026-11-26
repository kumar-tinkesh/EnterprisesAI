"""Which workspace a request works in, as a query condition.

Agents, workflows, runs, chats, approvals, schedules, share links, webhooks and
knowledge bases each belong to one workspace (``workspace_id``). A request only
sees rows of the workspace it is in (``CurrentUser.workspace_id``, checked
against membership on every request in ``src.api.deps``).

A caller without a workspace (a vendor admin, or a tenant that has none) is not
narrowed further than its tenant.
"""
from __future__ import annotations

from sqlalchemy import true


def in_workspace(column, user):
    """``Model.workspace_id == the caller's workspace`` (or no narrowing)."""
    wid = getattr(user, "workspace_id", None)
    return column == wid if wid else true()


def workspace_of(user) -> str | None:
    return getattr(user, "workspace_id", None)


def run_workspace(run_id: str):
    """For a new row that hangs off a run (an approval): the run's workspace,
    read in the same INSERT."""
    from sqlalchemy import select

    from builder.models import BuilderRun

    return select(BuilderRun.workspace_id).where(BuilderRun.id == run_id).scalar_subquery()


def target_workspace(kind: str, target_id: str):
    """For a new row about an agent or workflow (a chat, a schedule, a share
    link, a webhook): that agent's / workflow's workspace, read in the INSERT."""
    from sqlalchemy import select

    from builder.models import BuilderAgent, BuilderWorkflow

    model = BuilderAgent if kind == "agent" else BuilderWorkflow
    return select(model.workspace_id).where(model.id == target_id).scalar_subquery()
