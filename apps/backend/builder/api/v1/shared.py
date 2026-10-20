"""Share links (mounted at ``/api/v1/shared``): run a published agent/workflow
from a link, signed in.

    GET  /{slug}                        what the link runs: name, who shared it, what to send (no login)
    GET  /{slug}/needs                  "visitor"/"mixed" links: the systems it uses and which I still have to connect
    POST /{slug}/runs                   run it: {"input": "...", "variables": {...}, "wait_seconds": 20}
                                        200 when it finished within wait_seconds, else 202 — then poll
    GET  /{slug}/runs                   my runs through this link, newest first
    GET  /{slug}/runs/{run_id}          one of them
    GET  /{slug}/runs/{run_id}/events   the same, live (SSE: builder.publishing.live) — the answer as it's written
    POST /{slug}/runs/{run_id}/cancel

The link belongs to a publishable key (``share_enabled``/``share_slug``, set
in builder.api.v1.publishing) and keeps that key's switches and limits, plus
``per_user_daily_limit`` per person; someone the publisher blocked
(``blocked_user_ids``) keeps their earlier runs but can't start new ones.

Whose tools (``tool_mode``):
* "publisher": a run executes as the key's maker, with their connected tools —
  so a data-changing call waits for THEIR approval, and the caller sees
  ``waiting_for: "approval"`` until they decide.
* "visitor": a run executes as the signed-in caller, with their own
  connections (they connect what's missing first — GET /needs), so the
  approvals are theirs too: a waiting run's view lists them, and they decide
  with POST /builder/approvals/{id} like any of their own. The publisher sees
  that they ran it and how often, never what was in it.
* "mixed": as "visitor", except the servers the publisher kept as theirs
  (``publisher_server_ids``): those calls use the publisher's account, and
  wait for the publisher's approval, not the caller's.

Callers see only their own runs, and of those only status, the answer, its
sources — and, on a visitor link, their own pending approvals.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db
from src.models import User

from builder.api.v1.public import _wait
from builder.models import BuilderApproval, BuilderPublicKey, BuilderRun
from builder.publishing.service import (
    PublishError, connection_needs, connection_problems, definition_for, input_fields, public_view, publisher, share_publisher_servers,
    start_public_run, target_of,
)
from builder.runs import states
from builder.publishing.ip_limit import check_ip_limit
from builder.publishing.live import SSE_HEADERS, caller_events
from builder.runs.db import as_utc, session_factory
from builder.runs.service import approval_view, cancel_run

router = APIRouter()


class SharedRunIn(BaseModel):
    input: str = Field(default="", max_length=8000)
    variables: dict = Field(default_factory=dict)
    wait_seconds: float = Field(default=20, ge=0, le=30)
    # Send the answer as it's written, on GET .../events (off: only the finished answer).
    stream: bool = True


def _fail(exc: PublishError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "problems": exc.problems})


async def _link(db: AsyncSession, slug: str) -> BuilderPublicKey:
    key = (await db.execute(select(BuilderPublicKey).where(BuilderPublicKey.share_slug == slug))).scalars().first()
    if key is None or key.status == "revoked" or not key.share_enabled:
        raise HTTPException(status_code=404, detail="This link doesn't work any more.")
    if key.status == "paused":
        raise HTTPException(status_code=403, detail="Whoever shared this has paused it for now.")
    return key


NEEDS_WORKSPACE = "This link uses your own connected apps, which needs an account with a workspace."


async def _view(db: AsyncSession, run: BuilderRun, user: CurrentUser) -> dict:
    view = {**public_view(run), "input": (run.input or {}).get("text") or "", "created_at": as_utc(run.created_at).isoformat(), "approvals": []}
    # A run as the caller (a visitor link) waits on THEIR decisions: show them here.
    if run.status == states.WAITING and run.owner_id == user.id:
        pending = (
            await db.execute(select(BuilderApproval).where(
                BuilderApproval.run_id == run.id, BuilderApproval.owner_id == user.id, BuilderApproval.status == states.APPROVAL_PENDING,
            ).order_by(BuilderApproval.created_at))
        ).scalars().all()
        view["approvals"] = [approval_view(a) for a in pending]
    return view


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
        "tool_mode": key.tool_mode or "publisher",
    }


@router.get("/{slug}/needs")
async def needs(slug: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """On a visitor/mixed link: every system it uses, whose account it uses and
    where it stands; ``problems`` empty = ready to run."""
    key = await _link(db, slug)
    mode = key.tool_mode or "publisher"
    if mode == "publisher":
        return {"tool_mode": mode, "systems": [], "problems": []}
    if not user.tenant_id:
        return {"tool_mode": mode, "systems": [], "problems": [NEEDS_WORKSPACE]}
    try:
        owner = await publisher(db, key)
        definition, _ = await definition_for(db, key.kind, await target_of(db, key), key.version)
    except PublishError as exc:
        return _fail(exc)
    owners = {sid: owner for sid in share_publisher_servers(key)}
    return {
        "tool_mode": mode,
        "systems": await connection_needs(db, user, definition, owners),
        "problems": await connection_problems(db, user, definition, owners),
    }


@router.post("/{slug}/runs")
async def start(
    slug: str, payload: SharedRunIn, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    key = await _link(db, slug)
    await check_ip_limit(request)
    if user.id in (key.blocked_user_ids or []):
        raise HTTPException(status_code=403, detail="Whoever shared this has turned off your access to it.")
    visitor = key.tool_mode in ("visitor", "mixed")
    if visitor and not user.tenant_id:
        raise HTTPException(status_code=403, detail=NEEDS_WORKSPACE)
    try:
        run = await start_public_run(
            db, key, text=payload.input, variables=payload.variables, caller_user_id=user.id, run_as=user if visitor else None,
            stream=payload.stream,
        )
    except PublishError as exc:
        return _fail(exc)
    run = await _wait(db, run.id, payload.wait_seconds)
    return JSONResponse(status_code=200 if run.status in states.TERMINAL else 202, content=await _view(db, run, user))


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
    return [await _view(db, r, user) for r in runs]


@router.get("/{slug}/runs/{run_id}")
async def read(slug: str, run_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    return await _view(db, await _own_run(db, key, run_id, user), user)


@router.get("/{slug}/runs/{run_id}/events")
async def events(slug: str, run_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    await _own_run(db, key, run_id, user)

    async def view() -> dict:
        async with session_factory() as fresh:
            return await _view(fresh, await fresh.get(BuilderRun, run_id), user)

    return StreamingResponse(caller_events(run_id, view), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{slug}/runs/{run_id}/cancel")
async def cancel(slug: str, run_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    key = await _link(db, slug)
    run = await _own_run(db, key, run_id, user)
    await cancel_run(db, run)
    return await _view(db, run, user)
