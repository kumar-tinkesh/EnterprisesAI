"""The system prompt an agent runs with."""
from __future__ import annotations

from builder.agents.config import AgentConfig

_TONES = {
    "professional": "Write in a professional register: plain, precise, no filler.",
    "friendly": "Write warmly and plainly, as a helpful colleague would.",
    "concise": "Be brief. Answer and stop.",
    "technical": "Write for a technical reader: exact terms, no simplification.",
}
_VERBOSITY = {
    "concise": "Keep answers short: the answer first, only the detail that matters.",
    "detailed": "Give a thorough answer with the relevant detail and reasoning.",
}
_TOOL_RULES = (
    "Use your tools to get facts and to take actions; never invent what a tool would have returned. "
    "If a tool fails or returns nothing useful, say so plainly instead of guessing. "
    "If a tool you need is missing, say what you would need."
)


def response_rules(config: AgentConfig) -> list[str]:
    """Ported from the AI Marketplace's ``ResponseSettings.prompt_block``."""
    r = config.response
    lines: list[str] = []
    if r.tone in _TONES:
        lines.append(_TONES[r.tone])
    elif r.tone:
        lines.append(r.tone)
    if r.verbosity in _VERBOSITY:
        lines.append(_VERBOSITY[r.verbosity])
    if r.language and r.language != "auto":
        lines.append(f"Answer in {r.language}, whatever language the question is in.")
    if r.formats:
        allowed = ", ".join(sorted(r.formats))
        excluded = sorted({"markdown", "tables", "code", "bullets"} - set(r.formats))
        line = f"Formatting: use ONLY {allowed}."
        if excluded:
            line += f" Do not use {', '.join(excluded)}."
        lines.append(line)
    if r.citations == "always":
        lines.append("Cite the source for every factual claim you make.")
    elif r.citations == "off":
        lines.append("Do not add source citations.")
    return lines


def system_prompt(agent: dict, config: AgentConfig, *, has_tools: bool, has_knowledge: bool) -> str:
    parts = [f"You are {agent['name']}, {agent['role']}.", f"Your goal: {agent['goal']}"]
    if agent.get("instructions"):
        parts.append(f"Instructions:\n{agent['instructions']}")
    if has_tools:
        parts.append(_TOOL_RULES)
    if has_knowledge:
        parts.append("For questions about the organisation's own documents and policies, search the knowledge base first and answer from what it returns.")
    rules = response_rules(config)
    if rules:
        parts.append("How to answer:\n" + "\n".join(f"- {line}" for line in rules))
    return "\n\n".join(parts)


__all__ = ["system_prompt", "response_rules"]
