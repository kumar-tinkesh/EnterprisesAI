"""Running test cases against an agent or workflow, and grading them.

    start_test_run(db, user, kind, target, cases) -> BuilderTestRun
    on_run_finished(run_id)       grade the case whose run just ended (called by the worker)
    sweep()                       grade/finish anything a crash left behind (the worker's reaper)

Each case becomes a real run (``purpose="test"``) on the normal queue, so the
guardrails, tools and permissions being tested are exactly the live ones —
with two differences that make it safe to test: data-changing tool calls are
simulated (``CallSite.dry_run``) and approval steps pass on their own.
A run that couldn't start (a tool not connected, a required input missing)
is a result too: it scores 0 and says why, since that is what a real user
would hit.

When a case's run ends, a model judge grades the behaviour against the
case's expectation (0-1; 0.7 and up passes). The test run's score is the mean
of its cases, also broken down by what each category tests. Grading claims
the result first (``running`` -> ``grading``), so the worker's hook and the
reaper never grade the same case twice.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.assist.llm import AssistUnavailable, Usage, ask_json
from vendor.models import MCPTool

from builder.models import (
    BuilderAgent, BuilderRun, BuilderTestCase, BuilderTestResult, BuilderTestRun, BuilderToolCall, BuilderWorkflow,
)
from builder.quality.prompts import CATEGORIES, DIMENSIONS, judge_prompt
from builder.runs import states
from builder.runs.db import session_factory, utcnow
from builder.runs.service import cancel_run, create_agent_run, create_workflow_run
from builder.runs.start import agent_run_problems, workflow_run_problems
from builder.runs.tool_calls import DRY_RUN_RESULT

logger = logging.getLogger("builder.quality")

PASS_SCORE = 0.7
FALSE_CLAIM_CAP = 0.3
MAX_CASES = 25
RUNNING, GRADING, PASSED, FAILED, ERROR = "running", "grading", "passed", "failed", "error"


async def start_test_run(
    db: AsyncSession, user: CurrentUser, kind: str, target: BuilderAgent | BuilderWorkflow, cases: list[BuilderTestCase]
) -> BuilderTestRun:
    test_run = BuilderTestRun(
        tenant_id=user.tenant_id, owner_id=user.id, kind=kind, definition_version=target.version,
        total=len(cases), status=RUNNING, dimensions={},
        **({"agent_id": target.id} if kind == "agent" else {"workflow_id": target.id}),
    )
    db.add(test_run)
    await db.flush()
    test_run_id = test_run.id
    for case in cases:
        result = BuilderTestResult(
            test_run_id=test_run_id, case_id=case.id, title=case.title, category=case.category,
            input=case.input, expectation=case.expectation, status=RUNNING,
        )
        db.add(result)
        await db.flush()
        # The same checks as pressing Run: a test that can't start is a finding too.
        if kind == "agent":
            problems = await agent_run_problems(db, user, target)
        else:
            problems = await workflow_run_problems(db, user, target, case.variables or {})
        if problems or (kind == "agent" and not case.input.strip()):
            reason = " ".join(p.message for p in problems) or "The test has no request."
            result.status, result.score, result.reasoning = ERROR, 0.0, f"Couldn't run: {reason}"
            await db.commit()
            continue
        if kind == "agent":
            run = await create_agent_run(db, user, target, text=case.input, purpose="test")
        else:
            run = await create_workflow_run(db, user, target, text=case.input, variables=case.variables or {}, purpose="test")
        result.run_id = run.id
        await db.commit()
    test_run = await db.get(BuilderTestRun, test_run_id)
    await _finish_if_done(db, test_run_id)
    await db.refresh(test_run)
    return test_run


# ── grading ─────────────────────────────────────────────────────────────────


async def _evidence(db: AsyncSession, run: BuilderRun) -> str:
    calls = (
        await db.execute(select(BuilderToolCall).where(BuilderToolCall.run_id == run.id).order_by(BuilderToolCall.created_at))
    ).scalars().all()
    # What each tool does, so the judge can tell "echo" from "send_note".
    pairs = {(c.server_id, c.tool_name) for c in calls}
    described = {
        (t.mcp_server_id, t.name): (t.description or "").strip()[:160]
        for t in (await db.execute(select(MCPTool).where(MCPTool.name.in_({n for _, n in pairs})))).scalars()
        if (t.mcp_server_id, t.name) in pairs
    } if pairs else {}
    lines = []
    for c in calls[:20]:
        simulated = c.result_text == DRY_RUN_RESULT
        what = described.get((c.server_id, c.tool_name))
        kind = "read-only: it cannot save, send or change anything" if c.risk == "read" else f"changes data ({c.risk})"
        head = f"- called {c.tool_name}" + (f" — {what}" if what else "") + f" [{kind}] with {str(c.arguments)[:300]}"
        if simulated:
            lines.append(head + " -> SIMULATED write (counts as done)")
        else:
            lines.append(head + f" -> {'error' if c.is_error else c.status}: {(c.result_text or c.error or '')[:300]}")
    for g in (run.output or {}).get("guardrails") or []:
        lines.append(f"- guardrail: {g.get('message')}")
    if run.status != states.SUCCEEDED:
        lines.append(f"- the run ended {run.status}" + (f": {run.error}" if run.error else ""))
    return "\n".join(lines) or "(no tool calls)"


_WRITE_WORDS = re.compile(r"\b(sav|sen[dt]|creat|updat|delet|remov|book|post|email|mail|schedul|add|writ|stor|record|submit|cancel|chang|modif)", re.I)


def _unbacked_claims(verdict: dict, read_only: set[str]) -> list[str]:
    """Actions the answer claims that no tool call actually did: ones the judge
    found no call for, and data-changing claims it pinned on a read-only tool
    (judges rationalise "echo" as having saved something)."""
    out = []
    for c in verdict.get("claims") or []:
        if not isinstance(c, dict):
            continue
        action = str(c.get("action") or "an action")[:120]
        tool = str(c.get("tool_call") or "none").strip()
        if tool.lower() in ("none", "", "null", "n/a") or (tool in read_only and _WRITE_WORDS.search(action)):
            out.append(action)
    return out


async def grade_result(result_id: str) -> bool:
    """Grade one case whose run has ended. False if it isn't ready or someone else is grading it."""
    async with session_factory() as db:
        result = await db.get(BuilderTestResult, result_id)
        if result is None or result.status != RUNNING or not result.run_id:
            return False
        run = await db.get(BuilderRun, result.run_id)
        if run is None or run.status not in states.TERMINAL:
            return False
        claimed = await db.execute(
            update(BuilderTestResult).where(BuilderTestResult.id == result_id, BuilderTestResult.status == RUNNING)
            .values(status=GRADING).execution_options(synchronize_session=False)
        )
        await db.commit()
        if claimed.rowcount != 1:
            return False

        answer = run.output_text or ""
        usage = Usage()
        try:
            verdict = await ask_json(
                judge_prompt(result.input, result.expectation, answer or "(no answer — the run did not finish)", await _evidence(db, run)),
                usage, max_tokens=400,
            )
            score = max(0.0, min(1.0, float(verdict.get("score", 0.0))))
            reasoning = str(verdict.get("reasoning") or "")[:1000]
            read_only = set((await db.execute(
                select(BuilderToolCall.tool_name).where(BuilderToolCall.run_id == run.id, BuilderToolCall.risk == "read")
            )).scalars())
            unbacked = _unbacked_claims(verdict, read_only)
            if unbacked and score > FALSE_CLAIM_CAP:
                # Models note a false claim and still pass it; claiming an action
                # nothing performed is a failure whatever else went right.
                score = FALSE_CLAIM_CAP
                reasoning = f"Claims it did something no tool call did ({'; '.join(unbacked[:2])}). " + reasoning
            status = PASSED if score >= PASS_SCORE else FAILED
        except (AssistUnavailable, ValueError, TypeError) as exc:
            score, status, reasoning = None, ERROR, f"Couldn't be judged: {exc}"
        await db.refresh(result)
        result.status, result.score, result.reasoning = status, score, reasoning
        result.answer = (answer or run.error or "")[:20_000]
        test_run = await db.get(BuilderTestRun, result.test_run_id)
        test_run.judge_tokens = (test_run.judge_tokens or 0) + usage.prompt_tokens + usage.completion_tokens
        await db.commit()
        await _finish_if_done(db, result.test_run_id)
        return True


async def _finish_if_done(db: AsyncSession, test_run_id: str) -> None:
    test_run = await db.get(BuilderTestRun, test_run_id)
    if test_run is None or test_run.status != RUNNING:
        return
    results = (await db.execute(select(BuilderTestResult).where(BuilderTestResult.test_run_id == test_run_id))).scalars().all()
    if any(r.status in (RUNNING, GRADING) for r in results):
        return
    scored = [r for r in results if r.score is not None]
    test_run.passed = sum(1 for r in results if r.status == PASSED)
    test_run.score = round(100 * sum(r.score for r in scored) / len(scored)) if scored else None
    by_dim: dict[str, list[float]] = {}
    for r in scored:
        by_dim.setdefault(CATEGORIES.get(r.category, ("", "behaviour"))[1], []).append(r.score)
    test_run.dimensions = {d: round(100 * sum(v) / len(v)) for d in DIMENSIONS if (v := by_dim.get(d))}
    test_run.status, test_run.finished_at = "done", utcnow()
    await db.commit()


async def on_run_finished(run_id: str) -> None:
    """The worker calls this after every run it executed; only test runs have work to do."""
    async with session_factory() as db:
        result_id = (
            await db.execute(select(BuilderTestResult.id).where(BuilderTestResult.run_id == run_id, BuilderTestResult.status == RUNNING))
        ).scalar_one_or_none()
    if result_id:
        await grade_result(result_id)


async def sweep() -> int:
    """Grade cases whose run ended without being graded (a crash between the two),
    and free gradings a crashed worker left half-done."""
    async with session_factory() as db:
        stale = utcnow() - timedelta(minutes=10)
        await db.execute(
            update(BuilderTestResult).where(BuilderTestResult.status == GRADING, BuilderTestResult.updated_at < stale)
            .values(status=RUNNING).execution_options(synchronize_session=False)
        )
        await db.commit()
        ready = (
            await db.execute(
                select(BuilderTestResult.id).join(BuilderRun, BuilderRun.id == BuilderTestResult.run_id)
                .where(BuilderTestResult.status == RUNNING, BuilderRun.status.in_(list(states.TERMINAL))).limit(50)
            )
        ).scalars().all()
    graded = 0
    for result_id in ready:
        graded += await grade_result(result_id)
    return graded


async def cancel_test_run(db: AsyncSession, test_run: BuilderTestRun) -> None:
    results = (
        await db.execute(select(BuilderTestResult).where(BuilderTestResult.test_run_id == test_run.id, BuilderTestResult.status.in_([RUNNING, GRADING])))
    ).scalars().all()
    for r in results:
        if r.run_id and (run := await db.get(BuilderRun, r.run_id)) is not None:
            await cancel_run(db, run)
        r.status, r.reasoning = ERROR, "Cancelled."
    test_run.status, test_run.finished_at = "cancelled", utcnow()
    await db.commit()


__all__ = ["start_test_run", "grade_result", "on_run_finished", "sweep", "cancel_test_run", "PASS_SCORE", "MAX_CASES"]
