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
    reasoning: Optional[str] = None  # Extracted <think>...</think> reasoning trace
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
    reasoning: Optional[str] = None  # Thinking/reasoning delta (if inside <think>)
    finish_reason: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)


# ── Thinking / Reasoning Parsing Helpers ────────────────────────────────────

import re

_THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def extract_think_block(content: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Extracts <think>...</think> blocks from response content.
    Returns tuple of (clean_content, reasoning_text).
    """
    if not content:
        return content, None

    matches = _THINK_PATTERN.findall(content)
    if not matches:
        return content, None

    reasoning = "\n\n".join(m.strip() for m in matches if m.strip())
    clean_content = _THINK_PATTERN.sub("", content).strip()
    return clean_content, reasoning


class ReasoningStreamParser:
    """
    Stream parser that intercepts <think>...</think> tags during streaming.
    Populates chunk.reasoning with thinking text and chunk.content with clean response text.
    """

    def __init__(self) -> None:
        self.in_think: bool = False
        self.buffer: str = ""

    def process(self, chunk: StreamChunk) -> StreamChunk:
        if not chunk.content:
            return chunk

        self.buffer += chunk.content
        new_content = ""
        new_reasoning = ""

        while self.buffer:
            if not self.in_think:
                if "<think>" in self.buffer:
                    idx = self.buffer.find("<think>")
                    new_content += self.buffer[:idx]
                    self.buffer = self.buffer[idx + 7:]
                    self.in_think = True
                else:
                    # Check for partial tag match at end of buffer
                    partial = False
                    for i in range(1, 7):
                        if "<think>"[:i] == self.buffer[-i:]:
                            new_content += self.buffer[:-i]
                            self.buffer = self.buffer[-i:]
                            partial = True
                            break
                    if not partial:
                        new_content += self.buffer
                        self.buffer = ""
            else:
                if "</think>" in self.buffer:
                    idx = self.buffer.find("</think>")
                    new_reasoning += self.buffer[:idx]
                    self.buffer = self.buffer[idx + 8:]
                    self.in_think = False
                else:
                    # Check for partial tag match at end of buffer
                    partial = False
                    for i in range(1, 8):
                        if "</think>"[:i] == self.buffer[-i:]:
                            new_reasoning += self.buffer[:-i]
                            self.buffer = self.buffer[-i:]
                            partial = True
                            break
                    if not partial:
                        new_reasoning += self.buffer
                        self.buffer = ""

        return StreamChunk(
            content=new_content,
            reasoning=new_reasoning if new_reasoning else None,
            finish_reason=chunk.finish_reason,
            tool_calls=chunk.tool_calls,
        )


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
