"""Version history (mounted at ``/api/v1/builder``).

    GET  /agents/{agent_id}/versions                       saved versions, newest first
    GET  /agents/{agent_id}/versions/{version}             one version, with its full definition
    POST /agents/{agent_id}/versions/{version}/restore     bring it back (as a new version)
    GET  /workflows/{workflow_id}/versions
    GET  /workflows/{workflow_id}/versions/{version}
    POST /workflows/{workflow_id}/versions/{version}/restore

Anyone in the workspace can look at the history; restoring is a change, so it
is for the creator or a tenant admin, and takes ``expected_version`` like any
save (someone else may have saved in the meantime).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db
from src.models import User

from builder.api.v1.agents import agent_out, get_agent
from builder.api.v1.deps import can_manage, get_end_user, problems_response, version_conflict
from builder.api.v1.workflows import _get_workflow, _workflow_out
from builder.models import BuilderVersion
from builder.runs.db import as_utc
from builder.versions.service import RestoreError, restore_agent, restore_workflow

router = APIRouter()


class VersionOut(BaseModel):
    id: str
    version: int
    note: str
    summary: str
    author_id: str | None
    author_name: str | None
    created_at: datetime
    is_current: bool


class VersionDetail(VersionOut):
    snapshot: dict[str, Any]


class RestoreRequest(BaseModel):
    expected_version: int | None = None


async def _authors(db: AsyncSession, rows: list[BuilderVersion]) -> dict[str, str]:
    ids = {r.author_id for r in rows if r.author_id}
    if not ids:
        return {}
    users = (await db.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
    return {u.id: u.full_name or u.email for u in users}


def _out(row: BuilderVersion, current: int, authors: dict[str, str]) -> dict:
    return {
        "id": row.id, "version": row.version, "note": row.note, "summary": row.summary,
        "author_id": row.author_id, "author_name": authors.get(row.author_id or ""),
        "created_at": as_utc(row.created_at), "is_current": row.version == current,
    }


async def _list(db: AsyncSession, column, target_id: str, current: int) -> list[VersionOut]:
    rows = (await db.execute(select(BuilderVersion).where(column == target_id).order_by(BuilderVersion.version.desc()))).scalars().all()
    authors = await _authors(db, list(rows))
    return [VersionOut(**_out(r, current, authors)) for r in rows]


async def _one(db: AsyncSession, column, target_id: str, version: int) -> BuilderVersion:
    row = (
        await db.execute(select(BuilderVersion).where(column == target_id, BuilderVersion.version == version))
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Version {version} not found (old versions are pruned).")
    return row


# ── agents ──


@router.get("/agents/{agent_id}/versions", response_model=list[VersionOut])
async def list_agent_versions(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    return await _list(db, BuilderVersion.agent_id, agent.id, agent.version)


@router.get("/agents/{agent_id}/versions/{version}", response_model=VersionDetail)
async def read_agent_version(agent_id: str, version: int, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    row = await _one(db, BuilderVersion.agent_id, agent.id, version)
    return VersionDetail(**_out(row, agent.version, await _authors(db, [row])), snapshot=row.snapshot or {})


@router.post("/agents/{agent_id}/versions/{version}/restore")
async def restore_agent_version(
    agent_id: str, version: int, payload: RestoreRequest,
    user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    if not can_manage(agent.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the agent's creator or a tenant admin can restore a version.")
    if payload.expected_version is not None and payload.expected_version != agent.version:
        raise version_conflict(agent.version)
    row = await _one(db, BuilderVersion.agent_id, agent.id, version)
    try:
        await restore_agent(db, agent, row, user)
    except RestoreError as exc:
        await db.rollback()
        return problems_response(exc.message, exc.problems)
    await db.commit()
    await db.refresh(agent)
    return agent_out(agent, user)


# ── workflows ──


@router.get("/workflows/{workflow_id}/versions", response_model=list[VersionOut])
async def list_workflow_versions(workflow_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    wf = await _get_workflow(db, workflow_id, user)
    return await _list(db, BuilderVersion.workflow_id, wf.id, wf.version)


@router.get("/workflows/{workflow_id}/versions/{version}", response_model=VersionDetail)
async def read_workflow_version(workflow_id: str, version: int, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    wf = await _get_workflow(db, workflow_id, user)
    row = await _one(db, BuilderVersion.workflow_id, wf.id, version)
    return VersionDetail(**_out(row, wf.version, await _authors(db, [row])), snapshot=row.snapshot or {})


@router.post("/workflows/{workflow_id}/versions/{version}/restore")
async def restore_workflow_version(
    workflow_id: str, version: int, payload: RestoreRequest,
    user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db),
):
    wf = await _get_workflow(db, workflow_id, user)
    if not can_manage(wf.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the workflow's creator or a tenant admin can restore a version.")
    if payload.expected_version is not None and payload.expected_version != wf.version:
        raise version_conflict(wf.version)
    row = await _one(db, BuilderVersion.workflow_id, wf.id, version)
    try:
        await restore_workflow(db, wf, row, user)
    except RestoreError as exc:
        await db.rollback()
        return problems_response(exc.message, exc.problems)
    await db.commit()
    await db.refresh(wf)
    return await _workflow_out(db, wf, user)
