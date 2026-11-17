"""Workflow templates and tool-need status (mounted at ``/api/v1/builder``).

    GET  /templates                 the templates, each with its systems' status for the caller
    POST /templates/{key}           create a workflow from one (same checks as POST /workflows)
    POST /tool-needs/status         where each of these tool needs stands for the caller

A system's status is the caller's own (``builder.agents.needs``): ready,
not_connected (they can connect it in place), not_verified (the admin added
it but hasn't connected it) or missing (no such server yet).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.agents.config import ToolNeed
from builder.agents.needs import resolve_needs
from builder.api.v1.definitions import WorkflowCreate, WorkflowOut
from builder.api.v1.deps import get_end_user
from builder.api.v1.workflows import create_workflow
from builder.templates import TEMPLATES, template_needs

router = APIRouter()


class NeedStatusRequest(BaseModel):
    needs: list[ToolNeed] = Field(default_factory=list, max_length=50)


async def _systems(db: AsyncSession, user: CurrentUser, needs: list[dict]) -> list[dict]:
    return [s.as_dict() for s in await resolve_needs(db, user, [ToolNeed.model_validate(n) for n in needs])]


@router.get("/templates")
async def list_templates(user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    out = []
    for t in TEMPLATES.values():
        body = t["build"]()
        out.append({
            "key": t["key"], "name": t["name"], "summary": t["summary"], "description": body["description"],
            "steps": sum(1 for n in body["nodes"] if n["type"] == "agent"),
            "systems": await _systems(db, user, template_needs(body)),
        })
    return out


@router.post("/templates/{key}", response_model=WorkflowOut, status_code=201)
async def create_from_template(key: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    template = TEMPLATES.get(key)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return await create_workflow(WorkflowCreate.model_validate(template["build"]()), user=user, db=db)


@router.post("/tool-needs/status")
async def tool_needs_status(payload: NeedStatusRequest, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return [s.as_dict() for s in await resolve_needs(db, user, payload.needs)]
