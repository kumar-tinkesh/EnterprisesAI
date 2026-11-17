"""Testing agents and workflows (mounted at ``/api/v1/builder``).

    GET    /{agents|workflows}/{id}/tests             its test cases
    POST   /{agents|workflows}/{id}/tests             add one
    POST   /{agents|workflows}/{id}/tests/generate    have the AI write some (saved, editable)
    PATCH  /tests/{case_id}                           change one
    DELETE /tests/{case_id}
    POST   /{agents|workflows}/{id}/test-runs         run all (or some) cases against the current version
    GET    /{agents|workflows}/{id}/test-runs         my test runs of it, newest first (score per version)
    GET    /test-runs/{test_run_id}                   one test run, with every case's result
    POST   /test-runs/{test_run_id}/cancel

Test cases belong to the agent/workflow: its creator or a tenant admin writes
them. Anyone who can run it can run its tests — as themselves, with their own
connected tools, like pressing Run — and sees only their own test runs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.agents import get_agent
from builder.api.v1.assist import _unavailable
from builder.api.v1.deps import can_manage, get_end_user
from builder.api.v1.workflows import _get_workflow
from builder.assist.llm import AssistUnavailable, Usage
from builder.models import BuilderAgent, BuilderTestCase, BuilderTestResult, BuilderTestRun, BuilderWorkflow
from builder.quality.generate import generate_cases
from builder.quality.prompts import CATEGORIES, DEFAULT_CATEGORIES
from builder.quality.suite import MAX_CASES, cancel_test_run, start_test_run
from builder.runs.db import as_utc

router = APIRouter()

Kind = Literal["agents", "workflows"]
Category = Literal["normal", "ambiguous", "knowledge_gap", "tools", "safety", "injection", "out_of_scope"]


class CaseIn(BaseModel):
    title: str = Field(default="", max_length=200)
    input: str = Field(min_length=1, max_length=4000)
    expectation: str = Field(min_length=1, max_length=2000)
    category: Category = "normal"
    variables: dict[str, Any] = Field(default_factory=dict)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    input: str | None = Field(default=None, min_length=1, max_length=4000)
    expectation: str | None = Field(default=None, min_length=1, max_length=2000)
    category: Category | None = None
    variables: dict[str, Any] | None = None


class GenerateIn(BaseModel):
    count: int = Field(default=6, ge=1, le=12)
    categories: list[Category] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES))


class StartIn(BaseModel):
    # Default: every case.
    case_ids: list[str] | None = None


class CaseOut(BaseModel):
    id: str
    title: str
    input: str
    expectation: str
    category: str
    variables: dict[str, Any]
    source: str
    created_at: datetime


class ResultOut(BaseModel):
    id: str
    case_id: str | None
    run_id: str | None
    title: str
    category: str
    input: str
    expectation: str
    status: str
    score: float | None
    reasoning: str | None
    answer: str | None


class TestRunOut(BaseModel):
    id: str
    kind: str
    definition_version: int
    status: str
    score: int | None
    passed: int
    total: int
    dimensions: dict[str, int]
    created_at: datetime
    finished_at: datetime | None
    done: int = 0  # cases finished so far
    results: list[ResultOut] | None = None


async def _target(db: AsyncSession, kind: Kind, target_id: str, user: CurrentUser) -> BuilderAgent | BuilderWorkflow:
    return await get_agent(db, target_id, user) if kind == "agents" else await _get_workflow(db, target_id, user)


def _manage(target: BuilderAgent | BuilderWorkflow, user: CurrentUser) -> None:
    if not can_manage(target.owner_id, user):
        raise HTTPException(status_code=403, detail="Only its creator or a tenant admin can change its tests.")


def _cases_of(kind: Kind, target_id: str):
    return BuilderTestCase.agent_id == target_id if kind == "agents" else BuilderTestCase.workflow_id == target_id


def _case_out(c: BuilderTestCase) -> CaseOut:
    return CaseOut(id=c.id, title=c.title, input=c.input, expectation=c.expectation, category=c.category,
                   variables=c.variables or {}, source=c.source, created_at=as_utc(c.created_at))


async def _test_run_out(db: AsyncSession, t: BuilderTestRun, *, detail: bool) -> TestRunOut:
    results = (
        await db.execute(select(BuilderTestResult).where(BuilderTestResult.test_run_id == t.id).order_by(BuilderTestResult.created_at))
    ).scalars().all()
    out = TestRunOut(
        id=t.id, kind=t.kind, definition_version=t.definition_version, status=t.status, score=t.score,
        passed=t.passed, total=t.total, dimensions=t.dimensions or {}, created_at=as_utc(t.created_at),
        finished_at=as_utc(t.finished_at), done=sum(1 for r in results if r.status not in ("running", "grading")),
    )
    if detail:
        out.results = [
            ResultOut(id=r.id, case_id=r.case_id, run_id=r.run_id, title=r.title, category=r.category, input=r.input,
                      expectation=r.expectation, status=r.status, score=r.score, reasoning=r.reasoning, answer=r.answer)
            for r in results
        ]
    return out


async def _own_test_run(db: AsyncSession, test_run_id: str, user: CurrentUser) -> BuilderTestRun:
    t = (
        await db.execute(select(BuilderTestRun).where(BuilderTestRun.id == test_run_id, BuilderTestRun.owner_id == user.id))
    ).scalars().first()
    if t is None:
        raise HTTPException(status_code=404, detail="Test run not found.")
    return t


async def _case(db: AsyncSession, case_id: str, user: CurrentUser) -> tuple[BuilderTestCase, BuilderAgent | BuilderWorkflow]:
    case = (
        await db.execute(select(BuilderTestCase).where(BuilderTestCase.id == case_id, BuilderTestCase.tenant_id == user.tenant_id))
    ).scalars().first()
    if case is None:
        raise HTTPException(status_code=404, detail="Test case not found.")
    target = await (get_agent(db, case.agent_id, user) if case.agent_id else _get_workflow(db, case.workflow_id, user))
    return case, target


# ── test cases ──


@router.get("/{kind}/{target_id}/tests", response_model=list[CaseOut])
async def list_cases(kind: Kind, target_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    cases = (await db.execute(select(BuilderTestCase).where(_cases_of(kind, target.id)).order_by(BuilderTestCase.created_at))).scalars().all()
    return [_case_out(c) for c in cases]


@router.post("/{kind}/{target_id}/tests", response_model=CaseOut, status_code=201)
async def create_case(kind: Kind, target_id: str, payload: CaseIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    _manage(target, user)
    case = BuilderTestCase(
        tenant_id=target.tenant_id, title=(payload.title or payload.input)[:200].strip(), input=payload.input.strip(),
        expectation=payload.expectation.strip(), category=payload.category, variables=payload.variables,
        source="manual", created_by=user.id, **({"agent_id": target.id} if kind == "agents" else {"workflow_id": target.id}),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return _case_out(case)


@router.post("/{kind}/{target_id}/tests/generate", response_model=list[CaseOut], status_code=201)
async def generate(kind: Kind, target_id: str, payload: GenerateIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    _manage(target, user)
    try:
        drafts = await generate_cases(db, kind[:-1], target, count=payload.count, categories=list(payload.categories), usage=Usage())
    except AssistUnavailable as exc:
        raise _unavailable(exc) from exc
    if not drafts:
        raise HTTPException(status_code=502, detail="The AI didn't return usable test cases. Try again.")
    cases = [
        BuilderTestCase(tenant_id=target.tenant_id, source="generated", created_by=user.id, variables={},
                        **d, **({"agent_id": target.id} if kind == "agents" else {"workflow_id": target.id}))
        for d in drafts
    ]
    db.add_all(cases)
    await db.commit()
    return [_case_out(c) for c in cases]


@router.patch("/tests/{case_id}", response_model=CaseOut)
async def update_case(case_id: str, payload: CaseUpdate, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    case, target = await _case(db, case_id, user)
    _manage(target, user)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(case, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(case)
    return _case_out(case)


@router.delete("/tests/{case_id}", status_code=204)
async def delete_case(case_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    case, target = await _case(db, case_id, user)
    _manage(target, user)
    await db.delete(case)
    await db.commit()


# ── test runs ──


@router.post("/{kind}/{target_id}/test-runs", response_model=TestRunOut, status_code=201)
async def start(kind: Kind, target_id: str, payload: StartIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    query = select(BuilderTestCase).where(_cases_of(kind, target.id)).order_by(BuilderTestCase.created_at)
    if payload.case_ids is not None:
        query = query.where(BuilderTestCase.id.in_(payload.case_ids))
    cases = (await db.execute(query)).scalars().all()
    if not cases:
        raise HTTPException(status_code=422, detail="Add a test case first.")
    if len(cases) > MAX_CASES:
        raise HTTPException(status_code=422, detail=f"A test run takes at most {MAX_CASES} cases; pick fewer.")
    test_run = await start_test_run(db, user, kind[:-1], target, list(cases))
    return await _test_run_out(db, test_run, detail=True)


@router.get("/{kind}/{target_id}/test-runs", response_model=list[TestRunOut])
async def list_test_runs(kind: Kind, target_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    column = BuilderTestRun.agent_id if kind == "agents" else BuilderTestRun.workflow_id
    runs = (
        await db.execute(
            select(BuilderTestRun).where(column == target.id, BuilderTestRun.owner_id == user.id)
            .order_by(BuilderTestRun.created_at.desc()).limit(30)
        )
    ).scalars().all()
    return [await _test_run_out(db, t, detail=False) for t in runs]


@router.get("/test-runs/{test_run_id}", response_model=TestRunOut)
async def read_test_run(test_run_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return await _test_run_out(db, await _own_test_run(db, test_run_id, user), detail=True)


@router.post("/test-runs/{test_run_id}/cancel", response_model=TestRunOut)
async def cancel(test_run_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    t = await _own_test_run(db, test_run_id, user)
    if t.status == "running":
        await cancel_test_run(db, t)
    return await _test_run_out(db, t, detail=True)


@router.get("/test-categories")
async def categories(user: CurrentUser = Depends(get_end_user)):
    return [{"id": k, "description": v[0], "dimension": v[1]} for k, v in CATEGORIES.items()]
