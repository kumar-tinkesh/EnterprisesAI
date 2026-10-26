"""A workflow's front desk: is this message for the workflow, or just a greeting
or a general question?

    await decide(definition, text, history) -> {"route": "task"} | {"route": "general", "answer": ...}

A workflow is a fixed path: every message used to go all the way through it, so
"Hi" fetched emails and tried to send a WhatsApp message. Before its first step
runs (``WorkflowConfig.answer_general_questions``, on a run someone typed into —
see builder.workflows.engine), one quick model call reads the message against
what the workflow's steps do. Small talk and questions none of its steps is for
get a direct answer that ends with what the workflow can do, and no step runs.
Anything that might be a request for it — or when the call fails — runs the
workflow as before: a real request must never be answered as chit-chat.
"""
from __future__ import annotations

import json
import logging

from builder.publishing.outline import outline
from builder.runs.db import session_factory
from builder.workflows import text as T

logger = logging.getLogger("builder.workflows.front_desk")

TASK = {"route": "task"}
# Earlier turns of the conversation shown with the message (app chat sends them).
HISTORY_TURNS = 6


async def capabilities(definition: dict) -> list[str]:
    """What the workflow's working steps do, one line each — from the same
    outline a share link shows (step names, goals, apps; never instructions)."""
    async with session_factory() as db:
        info = await outline(db, "workflow", definition)
    lines = []
    for step in info["steps"]:
        if step["kind"] not in ("agent", "tool"):
            continue
        line = step["title"]
        if step.get("hint"):
            line += f" — {step['hint']}"
        if step.get("apps"):
            line += f" (uses {', '.join(step['apps'])})"
        lines.append(line)
    return lines


def _prompt(name: str, description: str, steps: list[str], text: str, history: list[dict]) -> str:
    earlier = "\n".join(
        f"{m['role']}: {str(m.get('content') or '')[:500]}" for m in history[-HISTORY_TURNS:] if m.get("role") in ("user", "assistant")
    )
    return "\n".join([
        f'You are the front desk of "{name}", an automated workflow.' + (f" {description}" if description else ""),
        "",
        "What its steps do:",
        *(f"- {s}" for s in steps or ["(no steps described)"]),
        "",
        *([f"Earlier in this conversation:\n{earlier}", ""] if earlier else []),
        "A person just sent this message:",
        f"<message>\n{text}\n</message>",
        "",
        "Decide where it goes:",
        '- "task": it asks for something these steps do, or could reasonably be a request for it — including anything '
        "about the topics, data or apps the steps handle. When in doubt, choose \"task\".",
        '- "general": a greeting, small talk, thanks, a question about what you can do, or a general question none of the '
        "steps is for.",
        "",
        'For "general", also write "answer": reply the way a helpful assistant would, in the same language and tone as the '
        "message — answer a general question fully from your own knowledge. Then end with a short list of what this "
        "workflow can do, based only on the steps above, phrased for the person (not as step names). Never say you have "
        "already done any of the steps.",
        "",
        'Return JSON only: {"route": "task"} or {"route": "general", "answer": "..."}',
    ])


async def decide(definition: dict, text: str, history: list[dict] | None = None) -> dict:
    """``{"route": "task"}`` or ``{"route": "general", "answer"}``, plus the call's
    ``prompt_tokens``/``completion_tokens`` when one was made."""
    from builder.workflows.nodes import quick_llm

    if not text.strip():
        return dict(TASK)
    workflow = definition.get("workflow") or {}
    try:
        steps = await capabilities(definition)
        raw, pt, ct = await quick_llm(
            _prompt(workflow.get("name") or "Workflow", workflow.get("description") or "", steps, text, history or []),
            json_mode=True,
        )
        parsed = json.loads(T.strip_json_fence(raw))
    except Exception as exc:  # noqa: BLE001 — unsure means run the workflow, as before
        logger.warning("front desk failed, running the workflow: %s", exc)
        return dict(TASK)
    answer = str(parsed.get("answer") or "").strip() if isinstance(parsed, dict) else ""
    if parsed.get("route") == "general" and answer:
        return {"route": "general", "answer": answer, "prompt_tokens": pt, "completion_tokens": ct}
    return {"route": "task", "prompt_tokens": pt, "completion_tokens": ct}


__all__ = ["capabilities", "decide"]
