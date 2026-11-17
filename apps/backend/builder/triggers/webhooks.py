"""Webhooks: run an agent when something posts to its URL.

    POST /api/v1/public/hooks/{token}

Anything that can call a URL can start the agent: a website form, Zapier or
Make, a Slack slash command or outgoing webhook, a mail service's inbound
route (forward email to it), a CI job. What was posted becomes the request:

* JSON or a form with a ``text`` / ``message`` / ``input`` / ``body`` /
  ``content`` / ``prompt`` field -> that field (Slack sends ``text``);
* any other JSON or form -> the fields, written out one per line;
* plain text -> the text.

The hook's ``instruction`` goes in front ("A new lead came in. Qualify it:").
It runs as the hook's owner with the same checks as a run they start; a
check that fails answers 422 with the reasons, and nothing runs. Rate
limited per hook (counted from its runs, so it holds across processes).
Slack's Events API URL check (``url_verification``) is answered.
"""
from __future__ import annotations

import json
import secrets
from datetime import timedelta
from urllib.parse import parse_qs

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from builder.models import BuilderAgent, BuilderRun, BuilderWebhook
from builder.publishing.service import PublishError, hash_key, publisher
from builder.runs.db import utcnow
from builder.runs.service import create_agent_run
from builder.runs.start import agent_run_problems

TOKEN_PREFIX = "eai_wh_"
MAX_TEXT = 8000
TEXT_FIELDS = ("text", "message", "input", "body", "content", "prompt")


def new_token() -> tuple[str, str, str]:
    """-> (the token, its hash, a display prefix)."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_key(token), token[: len(TOKEN_PREFIX) + 4]


def _flatten(data: dict) -> str:
    lines = []
    for key, value in data.items():
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        lines.append(f"{key}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines)


def payload_text(body: bytes, content_type: str) -> str:
    """What was posted, as the agent's request."""
    raw = body.decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    data: object = None
    if "json" in content_type or raw[:1] in "{[":
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
    elif "x-www-form-urlencoded" in content_type:
        data = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(raw, keep_blank_values=True).items()}
    if isinstance(data, dict):
        for field in TEXT_FIELDS:
            if isinstance(data.get(field), str) and data[field].strip():
                return data[field].strip()[:MAX_TEXT]
        return _flatten(data)[:MAX_TEXT]
    if data is not None:
        return json.dumps(data, ensure_ascii=False, indent=1)[:MAX_TEXT]
    return raw[:MAX_TEXT]


def slack_challenge(body: bytes) -> str | None:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("type") == "url_verification" and isinstance(data.get("challenge"), str):
        return data["challenge"]
    return None


async def hook_for(db: AsyncSession, token: str) -> BuilderWebhook:
    hook = (await db.execute(select(BuilderWebhook).where(BuilderWebhook.token_hash == hash_key(token)))).scalars().first()
    if hook is None:
        raise PublishError(404, "No webhook at this address.")
    if not hook.enabled:
        raise PublishError(403, "This webhook is turned off.")
    return hook


async def start_webhook_run(db: AsyncSession, hook: BuilderWebhook, text: str) -> BuilderRun:
    now = utcnow()
    recent = (
        await db.execute(
            select(func.count()).select_from(BuilderRun).where(
                BuilderRun.webhook_id == hook.id, BuilderRun.created_at >= now - timedelta(minutes=1)
            )
        )
    ).scalar_one()
    if recent >= hook.requests_per_minute:
        raise PublishError(429, f"Too many requests: this webhook allows {hook.requests_per_minute} a minute.")
    owner = await publisher(db, hook)  # same rule as a publishable key: its owner must still have access
    agent = await db.get(BuilderAgent, hook.agent_id)
    if agent is None or agent.tenant_id != hook.tenant_id:
        raise PublishError(410, "The agent this webhook runs no longer exists.")
    if not text.strip() and not hook.instruction.strip():
        raise PublishError(422, "Send something for the agent to work on.")
    request = f"{hook.instruction.strip()}\n\n{text}".strip() if hook.instruction.strip() else text
    problems = await agent_run_problems(db, owner, agent)
    if problems:
        raise PublishError(422, "The agent can't run right now.", [p.message for p in problems])
    run = await create_agent_run(db, owner, agent, text=request, webhook_id=hook.id)
    hook.last_used_at, hook.last_run_id = now, run.id
    await db.commit()
    return run


__all__ = ["TOKEN_PREFIX", "hook_for", "new_token", "payload_text", "slack_challenge", "start_webhook_run"]
