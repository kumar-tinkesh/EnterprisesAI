"""The public API (mounted at ``/api/v1/public``) — no login, a publishable key.

    GET  /info                    what this key runs: name, what to send, inputs
    POST /runs                    run it: {"input": "...", "variables": {...}, "wait_seconds": 20}
                                  200 when it finished within wait_seconds, else 202 — then poll
    GET  /runs/{run_id}           a run this key started
    POST /runs/{run_id}/cancel
    GET  /widget.js               a chat bubble for any website:
                                  <script src=".../api/v1/public/widget.js" data-key="eai_pk_..."></script>

Send the key as ``Authorization: Bearer eai_pk_...``. A key is publishable:
it only ever runs the one agent/workflow it was made for, so it may sit in a
web page; ``allowed_origins`` limits which sites' browsers may use it. A run
that has to wait for the publisher to approve a data-changing tool call comes
back as ``waiting_for: "approval"`` and continues once they decide.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db

from builder.models import BuilderPublicKey, BuilderRun
from builder.publishing.service import (
    PublishError, definition_for, hash_key, input_fields, public_view, start_public_run, target_of,
)
from builder.runs import states
from builder.runs.service import cancel_run

router = APIRouter()

WIDGET = (Path(__file__).resolve().parents[2] / "publishing" / "widget.js").read_text(encoding="utf-8")


class PublicRunIn(BaseModel):
    input: str = Field(default="", max_length=8000)
    variables: dict = Field(default_factory=dict)
    # How long to hold the request open for the answer (0 = return at once and poll).
    wait_seconds: float = Field(default=20, ge=0, le=30)


def _fail(exc: PublishError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "problems": exc.problems})


async def public_key(
    authorization: str | None = Header(default=None),
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> BuilderPublicKey:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Send a publishable key: Authorization: Bearer eai_pk_...")
    key = (
        await db.execute(select(BuilderPublicKey).where(BuilderPublicKey.key_hash == hash_key(authorization.split(" ", 1)[1].strip())))
    ).scalars().first()
    if key is None or key.status == "revoked":
        raise HTTPException(status_code=401, detail="This key isn't valid.")
    if key.status == "paused":
        raise HTTPException(status_code=403, detail="This key is paused by its owner.")
    # Browsers always send Origin on these calls; server-to-server callers don't, and can't be told apart anyway.
    if key.allowed_origins and origin and origin.rstrip("/") not in {o.rstrip("/") for o in key.allowed_origins}:
        raise HTTPException(status_code=403, detail="This key can't be used from this website.")
    return key


@router.get("/info")
async def info(key: BuilderPublicKey = Depends(public_key), db: AsyncSession = Depends(get_db)):
    try:
        target = await target_of(db, key)
        definition, version = await definition_for(db, key.kind, target, key.version)
    except PublishError as exc:
        return _fail(exc)
    if key.kind == "agent":
        a = definition["agent"]
        return {"kind": "agent", "name": a.get("name"), "description": a.get("goal") or "", "inputs": [], "version": version}
    w = definition["workflow"]
    return {"kind": "workflow", "name": w.get("name"), "description": getattr(target, "description", "") or "",
            "inputs": input_fields(definition), "version": version}


async def _wait(db: AsyncSession, run_id: str, seconds: float) -> BuilderRun:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        db.expire_all()
        run = await db.get(BuilderRun, run_id)
        if run.status in states.TERMINAL or run.status == states.WAITING or loop.time() >= deadline:
            return run
        await asyncio.sleep(0.4)


@router.post("/runs")
async def start(payload: PublicRunIn, key: BuilderPublicKey = Depends(public_key), db: AsyncSession = Depends(get_db)):
    try:
        run = await start_public_run(db, key, text=payload.input, variables=payload.variables)
    except PublishError as exc:
        return _fail(exc)
    run = await _wait(db, run.id, payload.wait_seconds)
    return JSONResponse(status_code=200 if run.status in states.TERMINAL else 202, content=public_view(run))


async def _own_run(db: AsyncSession, run_id: str, key: BuilderPublicKey) -> BuilderRun:
    run = (await db.execute(select(BuilderRun).where(BuilderRun.id == run_id, BuilderRun.public_key_id == key.id))).scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/runs/{run_id}")
async def read(run_id: str, key: BuilderPublicKey = Depends(public_key), db: AsyncSession = Depends(get_db)):
    return public_view(await _own_run(db, run_id, key))


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, key: BuilderPublicKey = Depends(public_key), db: AsyncSession = Depends(get_db)):
    run = await _own_run(db, run_id, key)
    await cancel_run(db, run)
    return public_view(run)


@router.get("/widget.js", include_in_schema=False)
async def widget():
    # ASCII-only on purpose (non-ASCII is \u-escaped), and labelled UTF-8, so it reads
    # right on any page whatever that page's own charset.
    return Response(WIDGET, media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
