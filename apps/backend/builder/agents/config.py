"""What an owner can configure on an agent (``BuilderAgent.config``).

One schema decides every key's name, default and allowed range — ported from
the AI Marketplace's ``engines/agent_settings.py``. Two deliberate changes:

* Out-of-range or misspelled settings are rejected on save (422) instead of
  being silently clamped or ignored, so a control on screen can't quietly do
  nothing.
* ``approvals`` (ask before running read / edit / delete tools) lives on the
  agent, matching the tool runtime's risk levels.

* ``guardrails`` (``builder.guardrails.engine``) are off unless switched on,
  so existing agents behave exactly as before.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from builder.graph.schema import ToolApprovalPolicy, parse_tool_id


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMSettings(_Strict):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=64, le=32_000)
    reasoning_effort: Literal["auto", "low", "medium", "high"] = "auto"
    stop_sequences: list[str] = Field(default_factory=list, max_length=4)


class ResponseSettings(_Strict):
    tone: str = Field(default="", max_length=300)
    verbosity: Literal["concise", "balanced", "detailed"] = "balanced"
    language: str = Field(default="auto", max_length=40)
    formats: list[Literal["markdown", "tables", "code", "bullets"]] = Field(default_factory=list)
    citations: Literal["off", "when_used", "always"] = "always"


class ToolSettings(_Strict):
    max_calls: int = Field(default=8, ge=1, le=20)
    timeout_seconds: float = Field(default=30.0, ge=5, le=300)
    on_failure: Literal["retry", "continue", "stop"] = "continue"
    # A turn's read-only calls run side by side (builder.agents.runtime); off for a system that rate-limits or
    # can't take two at once (a logged-in browser session such as LinkedIn).
    side_by_side: bool = True
    # Stop calling tools once the step has run this long and answer with what it has (a search lane that must not
    # hold up the steps waiting on it). None = only max_calls limits it.
    time_budget_seconds: float | None = Field(default=None, ge=10, le=1800)


class ReliabilitySettings(_Strict):
    retries: int = Field(default=0, ge=0, le=5)
    request_timeout_seconds: float | None = Field(default=None, ge=10, le=600)
    fallback_model: str = Field(default="", max_length=100)
    retry_on: list[Literal["rate_limit", "timeout", "server", "provider"]] = Field(
        default_factory=lambda: ["rate_limit", "timeout", "server"]
    )


class GuardrailSettings(_Strict):
    """Safety checks around every run of the agent (see builder.guardrails.engine)."""

    # The request: refuse ones that try to override the agent's instructions.
    injection: bool = False
    # Tool results (an email, a web page, a document): fence off instructions
    # hidden in them so the model treats them as data.
    tool_injection: bool = False
    # Replace personal data (emails, phones, cards, Aadhaar, PAN, …) before
    # the model sees the request / before anyone sees the answer.
    pii_input: bool = False
    pii_output: bool = False
    # Check the answer against what the knowledge base returned: "fast" =
    # local similarity (catches answers that left the documents), "llm" = a
    # claim-by-claim check (catches made-up details; one extra model call).
    groundedness: bool = False
    groundedness_mode: Literal["fast", "llm"] = "fast"
    groundedness_min: float = Field(default=0.45, ge=0, le=1)
    # Plain-language policies the answer must follow; told to the agent up
    # front and checked on every answer (one extra model call).
    custom_rules: list[str] = Field(default_factory=list, max_length=10)
    # A broken rule or an unsupported claim: deliver the answer with a warning
    # ("flag") or withhold it and fail the step ("block").
    on_violation: Literal["flag", "block"] = "flag"

    @field_validator("custom_rules")
    @classmethod
    def _rules(cls, value: list[str]) -> list[str]:
        rules = [r.strip() for r in value if r and r.strip()]
        too_long = [r for r in rules if len(r) > 300]
        if too_long:
            raise ValueError("each rule must be at most 300 characters")
        return list(dict.fromkeys(rules))

    def any_on(self) -> bool:
        return any((self.injection, self.tool_injection, self.pii_input, self.pii_output, self.groundedness, self.custom_rules))


class ChatSettings(_Strict):
    """What a person sees when they open a chat with the agent."""

    welcome: str = Field(default="", max_length=500)
    # Suggested first questions, shown as buttons on an empty chat.
    starters: list[str] = Field(default_factory=list, max_length=4)
    # Greetings and general questions its goal isn't for get a real answer, ending
    # with what it can help with (builder.agents.prompts) — not a refusal.
    answer_general: bool = True

    @field_validator("starters")
    @classmethod
    def _starters(cls, value: list[str]) -> list[str]:
        starters = [s.strip() for s in value if s and s.strip()]
        if any(len(s) > 200 for s in starters):
            raise ValueError("each starter must be at most 200 characters")
        return list(dict.fromkeys(starters))


class MemorySettings(_Strict):
    """Long-term memory (``builder.agents.memory``): facts the agent saves
    about each person it works for, given back to it in their later chats."""

    enabled: bool = False
    # The most it keeps per person; the oldest go first.
    max_items: int = Field(default=50, ge=5, le=200)


class ToolNeed(_Strict):
    """A system the agent uses, named by WHERE its MCP server comes from
    rather than by a server id — so it is picked up by itself once an admin
    adds that server and the person connects it (``builder.agents.needs``).

    ``match`` holds repo slugs or URLs ("stickerdaniel/linkedin-mcp-server",
    "mcp.newsmcp.com"); a server matches when one appears in its repo or
    endpoint, whatever the admin named it. ``tools`` are the tool names to
    give the agent; empty, or none of them on the server, means all its tools.
    ``required``: the step can't run without it. Otherwise a step with needs
    runs once at least one of them is connected.
    """

    system: str = Field(min_length=1, max_length=80)
    match: list[str] = Field(min_length=1, max_length=5)
    tools: list[str] = Field(default_factory=list, max_length=20)
    required: bool = False

    @field_validator("match")
    @classmethod
    def _match(cls, value: list[str]) -> list[str]:
        cleaned = [m.strip() for m in value if m and m.strip()]
        if not cleaned or any(len(m) < 3 or len(m) > 300 for m in cleaned):
            raise ValueError("each match must be a repo or URL of 3-300 characters")
        return list(dict.fromkeys(cleaned))


class AgentConfig(_Strict):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    # mcp:<server_id>:<tool_name>
    tool_ids: list[str] = Field(default_factory=list, max_length=50)
    # Systems whose tools are added at run time, once connected (ToolNeed).
    tool_needs: list[ToolNeed] = Field(default_factory=list, max_length=10)
    # None of its (optional) systems connected: the step still runs, without their tools, instead of stopping
    # the run — for an extra like a WhatsApp alert, whose instructions say what to answer then.
    runs_without_needs: bool = False
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=10)
    response: ResponseSettings = Field(default_factory=ResponseSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    reliability: ReliabilitySettings = Field(default_factory=ReliabilitySettings)
    approvals: ToolApprovalPolicy = Field(default_factory=ToolApprovalPolicy)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    # Other standalone agents it may hand a task to (each becomes a tool;
    # see builder.agents.handoff). One level deep: theirs aren't used.
    sub_agent_ids: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("tool_ids")
    @classmethod
    def _tool_refs(cls, value: list[str]) -> list[str]:
        bad = [t for t in value if parse_tool_id(t) is None]
        if bad:
            raise ValueError(f"not a tool reference (mcp:<server_id>:<tool_name>): {', '.join(bad[:3])}")
        return list(dict.fromkeys(value))

    @field_validator("knowledge_base_ids", "sub_agent_ids")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


Profile = Literal["quality", "balanced", "speed", "cost"]

# One-click presets for the guided agent setup: each writes these settings and
# leaves everything else alone. Speed and cost still allow a few tool calls —
# an agent with tools that can make only one usually can't finish its job.
AGENT_PROFILES: dict[str, dict] = {
    "quality": {
        "label": "Best quality", "summary": "Thinks harder and double-checks. Slower, costs more.",
        "config": {"llm": {"temperature": 0.3, "max_output_tokens": 4000, "reasoning_effort": "high"},
                   "tools": {"max_calls": 12}, "reliability": {"retries": 2}, "response": {"verbosity": "detailed"}},
    },
    "balanced": {
        "label": "Balanced", "summary": "Good answers at a sensible speed. Right for most agents.",
        "config": {"llm": {"temperature": 0.5, "max_output_tokens": None, "reasoning_effort": "auto"},
                   "tools": {"max_calls": 8}, "reliability": {"retries": 1}, "response": {"verbosity": "balanced"}},
    },
    "speed": {
        "label": "Fast", "summary": "Short, quick replies. Good for simple lookups.",
        "config": {"llm": {"temperature": 0.5, "max_output_tokens": 800, "reasoning_effort": "low"},
                   "tools": {"max_calls": 4}, "reliability": {"retries": 0}, "response": {"verbosity": "concise"}},
    },
    "cost": {
        "label": "Lowest cost", "summary": "Fewest tokens and tool calls. For simple, high-volume work.",
        "config": {"llm": {"temperature": 0.3, "max_output_tokens": 600, "reasoning_effort": "low"},
                   "tools": {"max_calls": 3}, "reliability": {"retries": 0}, "response": {"verbosity": "concise"}},
    },
}


def apply_profile(config: dict | None, profile: str) -> dict:
    """``config`` with a profile's settings written over it (unknown profile -> balanced)."""
    preset = AGENT_PROFILES.get(profile) or AGENT_PROFILES["balanced"]
    return merge_config(config, preset["config"])


# A workflow step may also run its agent on another model. These sit in the
# step's ``config_overrides`` beside the config keys, but belong to the agent.
STEP_MODEL_KEYS = ("llm_provider", "llm_model")


def split_step_overrides(overrides: dict | None) -> tuple[dict, dict]:
    """A step's overrides as (config overrides, {llm_provider/llm_model it sets})."""
    config = {k: v for k, v in (overrides or {}).items() if k not in STEP_MODEL_KEYS}
    model = {k: (overrides or {})[k] for k in STEP_MODEL_KEYS if (overrides or {}).get(k)}
    return config, model


def merge_config(base: dict | None, overrides: dict | None) -> dict:
    """An agent's config with a workflow step's ``config_overrides`` on top —
    nested sections merge key by key; lists and scalars are replaced."""
    merged = dict(base or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


__all__ = [
    "AGENT_PROFILES",
    "AgentConfig",
    "LLMSettings",
    "ResponseSettings",
    "ToolSettings",
    "ToolNeed",
    "ReliabilitySettings",
    "GuardrailSettings",
    "ChatSettings",
    "MemorySettings",
    "apply_profile",
    "merge_config",
    "split_step_overrides",
    "STEP_MODEL_KEYS",
]
