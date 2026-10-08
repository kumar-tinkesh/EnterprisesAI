"""What an owner can configure on an agent (``BuilderAgent.config``).

One schema decides every key's name, default and allowed range — ported from
the AI Marketplace's ``engines/agent_settings.py``. Two deliberate changes:

* Out-of-range or misspelled settings are rejected on save (422) instead of
  being silently clamped or ignored, so a control on screen can't quietly do
  nothing.
* ``approvals`` (ask before running read / edit / delete tools) lives on the
  agent, matching the tool runtime's risk levels.

``guardrails`` stays an open object until the guardrails phase defines it.
"""
from __future__ import annotations

from typing import Any, Literal

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


class ReliabilitySettings(_Strict):
    retries: int = Field(default=0, ge=0, le=5)
    request_timeout_seconds: float | None = Field(default=None, ge=10, le=600)
    fallback_model: str = Field(default="", max_length=100)
    retry_on: list[Literal["rate_limit", "timeout", "server", "provider"]] = Field(
        default_factory=lambda: ["rate_limit", "timeout", "server"]
    )


class AgentConfig(_Strict):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    # mcp:<server_id>:<tool_name>
    tool_ids: list[str] = Field(default_factory=list, max_length=50)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=10)
    response: ResponseSettings = Field(default_factory=ResponseSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    reliability: ReliabilitySettings = Field(default_factory=ReliabilitySettings)
    approvals: ToolApprovalPolicy = Field(default_factory=ToolApprovalPolicy)
    guardrails: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_ids")
    @classmethod
    def _tool_refs(cls, value: list[str]) -> list[str]:
        bad = [t for t in value if parse_tool_id(t) is None]
        if bad:
            raise ValueError(f"not a tool reference (mcp:<server_id>:<tool_name>): {', '.join(bad[:3])}")
        return list(dict.fromkeys(value))

    @field_validator("knowledge_base_ids")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


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
    "AgentConfig",
    "LLMSettings",
    "ResponseSettings",
    "ToolSettings",
    "ReliabilitySettings",
    "merge_config",
]
