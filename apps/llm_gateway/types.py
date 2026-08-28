"""
LLM Gateway — Shared types & data classes used across all providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


# ── Enums ────────────────────────────────────────────────────────────────────

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Provider(str, Enum):
    OPENAI = "openai"
    GROQ = "groq"
    GEMINI = "gemini"


# ── Message ──────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """A single chat message."""

    role: Role
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


# ── Tool definition ─────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """OpenAI-compatible function/tool schema."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── Tool call (in response) ─────────────────────────────────────────────────

@dataclass
class ToolCall:
    """A tool invocation returned by the model."""

    id: str
    name: str
    arguments: str  # JSON string


# ── Token usage ──────────────────────────────────────────────────────────────

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ── Completion response ─────────────────────────────────────────────────────

@dataclass
class CompletionResponse:
    """Normalised response returned by every provider client."""

    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    provider: str = ""
    finish_reason: Optional[str] = None
    raw: Optional[Any] = None  # original SDK response for debugging


# ── Streaming chunk ──────────────────────────────────────────────────────────

@dataclass
class StreamChunk:
    """A single delta in a streaming completion."""

    content: str = ""
    finish_reason: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)


# ── Embedding response ──────────────────────────────────────────────────────

@dataclass
class EmbeddingResponse:
    embeddings: list[list[float]] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)


# ── Completion request params ────────────────────────────────────────────────

@dataclass
class CompletionRequest:
    """
    Provider-agnostic request payload.
    All provider clients accept this as input.
    """

    messages: list[Message]
    model: Optional[str] = None  # None → use provider default
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    stop: Optional[list[str]] = None
    tools: Optional[list[ToolDefinition]] = None
    tool_choice: Optional[str | dict[str, Any]] = None
    response_format: Optional[dict[str, Any]] = None
    stream: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)  # tenant_id, trace_id etc.
