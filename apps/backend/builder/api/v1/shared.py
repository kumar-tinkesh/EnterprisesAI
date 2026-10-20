"""Share links (mounted at ``/api/v1/shared``): run a published agent/workflow
from a link, signed in.

    GET  /{slug}                        what the link runs: name, who shared it, what to send (no login)
    POST /{slug}/runs                   run it: {"input": "...", "variables": {...}, "wait_seconds": 20}
                                        200 when it finished within wait_seconds, else 202 — then poll
    GET  /{slug}/runs                   my runs through this link, newest first
    GET  /{slug}/runs/{run_id}          one of them
    POST /{slug}/runs/{run_id}/cancel

The link belongs to a publishable key (``share_enabled``/``share_slug``, set
in builder.api.v1.publishing) and keeps that key's switches and limits, plus
``per_user_daily_limit`` per person. A run executes as the key's maker, with
their connected tools — so a data-changing call waits for THEIR approval, and
the caller sees ``waiting_for: "approval"`` until they decide. Callers see
only their own runs, and of those only status, the answer and its sources.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db
from src.models import User

from builder.api.v1.public import _wait
from builder.models import BuilderPublicKey, BuilderRun
from builder.publishing.service import PublishError, definition_for, input_fields, public_view, start_public_run, target_of
from builder.runs import states
from builder.runs.db import as_utc
from builder.runs.service import cancel_run

router = APIRouter()


class SharedRunIn(BaseModel):
    input: str = Field(default="", max_length=8000)
    variables: dict = Field(default_factory=dict)
    wait_seconds: float = Field(default=20, ge=0, le=30)


def _fail(exc: PublishError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "problems": exc.problems})


async def _link(db: AsyncSession, slug: str) -> BuilderPublicKey:
    key = (await db.execute(select(BuilderPublicKey).where(BuilderPublicKey.share_slug == slug))).scalars().first()
    if key is None or key.status == "revoked" or not key.share_enabled:
        raise HTTPException(status_code=404, detail="This link doesn't work any more.")
    if key.status == "paused":
        raise HTTPException(status_code=403, detail="Whoever shared this has paused it for now.")
    return key


def _view(run: BuilderRun) -> dict:
    return {**public_view(run), "input": (run.input or {}).get("text") or "", "created_at": as_utc(run.created_at).isoformat()}


async def _own_run(db: AsyncSession, key: BuilderPublicKey, run_id: str, user: CurrentUser) -> BuilderRun:
    run = (
        await db.execute(select(BuilderRun).where(
            BuilderRun.id == run_id, BuilderRun.public_key_id == key.id, BuilderRun.caller_user_id == user.id,
        ))
    ).scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/{slug}")
async def info(slug: str, db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    try:
        target = await target_of(db, key)
        definition, version = await definition_for(db, key.kind, target, key.version)
    except PublishError as exc:
        return _fail(exc)
    owner = await db.get(User, key.owner_id)
    if key.kind == "agent":
        a = definition["agent"]
        name, description, inputs = a.get("name"), a.get("goal") or "", []
    else:
        name, description, inputs = definition["workflow"].get("name"), getattr(target, "description", "") or "", input_fields(definition)
    return {
        "kind": key.kind, "name": name, "description": description, "inputs": inputs, "version": version,
        "shared_by": (owner.full_name or "").strip() if owner else "", "per_user_daily_limit": key.per_user_daily_limit,
    }


@router.post("/{slug}/runs")
async def start(slug: str, payload: SharedRunIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    try:
        run = await start_public_run(db, key, text=payload.input, variables=payload.variables, caller_user_id=user.id)
    except PublishError as exc:
        return _fail(exc)
    run = await _wait(db, run.id, payload.wait_seconds)
    return JSONResponse(status_code=200 if run.status in states.TERMINAL else 202, content=_view(run))


@router.get("/{slug}/runs")
async def my_runs(slug: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    runs = (
        await db.execute(
            select(BuilderRun)
            .where(BuilderRun.public_key_id == key.id, BuilderRun.caller_user_id == user.id)
            .order_by(BuilderRun.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [_view(r) for r in runs]


@router.get("/{slug}/runs/{run_id}")
async def read(slug: str, run_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    return _view(await _own_run(db, key, run_id, user))


@router.post("/{slug}/runs/{run_id}/cancel")
async def cancel(slug: str, run_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    run = await _own_run(db, key, run_id, user)
    await cancel_run(db, run)
    return _view(run)
