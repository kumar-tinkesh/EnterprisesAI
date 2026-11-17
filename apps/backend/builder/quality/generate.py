"""Write test cases for an agent or workflow from its own definition.

The model is shown what the thing does — its goal, instructions, tools (with
their risk level), knowledge bases, guardrails, or a workflow's steps — and
asked for realistic requests across the chosen kinds of trouble, each with the
behaviour a good response shows. Cases come back as drafts; the API saves
them so they can be edited or deleted like hand-written ones.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge.models import KnowledgeBase

from builder.agents.config import AgentConfig
from builder.agents.tools import resolve_agent_tools
from builder.assist.llm import Usage, ask_json
from builder.models import BuilderAgent, BuilderWorkflow
from builder.quality.prompts import CATEGORIES, generate_prompt
from builder.services.tool_runtime import classify_tool


async def _kb_names(db: AsyncSession, tenant_id: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    return list((await db.execute(select(KnowledgeBase.name).where(KnowledgeBase.id.in_(ids), KnowledgeBase.tenant_id == tenant_id))).scalars())


async def _agent_lines(db: AsyncSession, tenant_id: str, agent: dict) -> list[str]:
    config = AgentConfig.model_validate(agent.get("config") or {})
    tools = await resolve_agent_tools(db, config.tool_ids)
    tool_text = "; ".join(
        f"{t.server_name}.{t.tool_name} [{classify_tool(t.tool_name, t.annotations).risk}]: {(t.description or '')[:120]}" for t in tools
    ) or "none"
    g = config.guardrails
    guards = [name for name, on in (("refuses prompt injection", g.injection), ("fences off instructions in tool results", g.tool_injection),
                                    ("hides personal data from the model", g.pii_input), ("hides personal data in answers", g.pii_output),
                                    ("checks answers against its knowledge", g.groundedness)) if on]
    lines = [
        f"Name: {agent.get('name')}", f"Role: {agent.get('role')}", f"Goal: {agent.get('goal')}",
        f"Instructions: {(agent.get('instructions') or '(none)')[:1500]}",
        f"Tools (risk in brackets): {tool_text}",
        f"Knowledge bases: {', '.join(await _kb_names(db, tenant_id, config.knowledge_base_ids)) or 'none'}",
        f"Guardrails: {', '.join(guards) or 'none'}",
    ]
    if g.custom_rules:
        lines.append("Rules it must follow: " + " | ".join(g.custom_rules))
    return lines


async def summarize(db: AsyncSession, kind: str, target: BuilderAgent | BuilderWorkflow) -> str:
    if kind == "agent":
        return "\n".join(await _agent_lines(db, target.tenant_id, {
            "name": target.name, "role": target.role, "goal": target.goal, "instructions": target.instructions, "config": target.config,
        }))
    lines = [f"Workflow: {target.name}", f"Description: {target.description or '(none)'}", "Steps, in order:"]
    agent_ids = [n.get("agent_id") for n in target.nodes or [] if n.get("type") == "agent" and n.get("agent_id")]
    agents = {a.id: a for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(agent_ids)))).scalars()} if agent_ids else {}
    for n in target.nodes or []:
        label = n.get("label") or n.get("type")
        if n.get("type") == "agent" and (a := agents.get(n.get("agent_id") or "")):
            lines.append(f"- agent step \"{a.name}\": {a.goal}")
        elif n.get("type") == "tool":
            lines.append(f"- tool step \"{label}\": {n.get('need') or n.get('tool_id')}")
        elif n.get("type") == "condition":
            lines.append(f"- decision \"{label}\": {(n.get('condition_config') or {}).get('instructions') or 'picks a branch'}")
        else:
            lines.append(f"- {n.get('type')} \"{label}\"")
        for v in n.get("variables") or []:
            lines.append(f"  input field {v.get('name')}{' (required)' if v.get('required') else ''}")
    return "\n".join(lines)


async def generate_cases(
    db: AsyncSession, kind: str, target: BuilderAgent | BuilderWorkflow, *, count: int, categories: list[str], usage: Usage
) -> list[dict]:
    """Drafts: [{title, category, input, expectation}] — invalid ones dropped."""
    categories = [c for c in categories if c in CATEGORIES] or ["normal"]
    data = await ask_json(generate_prompt(kind, await summarize(db, kind, target), categories, count), usage, max_tokens=4000)
    cases = []
    for c in (data.get("cases") or [])[:count]:
        if not isinstance(c, dict):
            continue
        title, text, expectation = (str(c.get(k) or "").strip() for k in ("title", "input", "expectation"))
        if not (text and expectation):
            continue
        category = c.get("category") if c.get("category") in categories else categories[0]
        cases.append({"title": (title or text)[:200], "category": category, "input": text[:4000], "expectation": expectation[:2000]})
    return cases


__all__ = ["summarize", "generate_cases"]
