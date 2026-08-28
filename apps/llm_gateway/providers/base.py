"""
LLM Gateway — Abstract base class for all provider clients.

Every provider (OpenAI, Groq, Gemini) inherits from BaseLLMClient and
implements the same interface so the gateway can swap providers transparently.
"""

from __future__ import annotations

import abc
import logging
from typing import AsyncIterator, Optional

from apps.llm_gateway.config import ProviderConfig
from apps.llm_gateway.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    StreamChunk,
)

logger = logging.getLogger("llm_gateway")


class BaseLLMClient(abc.ABC):
    """
    Contract that every LLM provider client must satisfy.

    Sub-classes are thin wrappers around the provider's async SDK that
    normalise every response into the shared gateway types defined in
    ``types.py``.
    """

    PROVIDER_NAME: str = "base"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    # ── chat completion (non-streaming) ──────────────────────────────────

    @abc.abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send a chat-completion request and return the full response."""
        ...

    # ── chat completion (streaming) ──────────────────────────────────────

    @abc.abstractmethod
    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Yield streaming deltas for a chat-completion request."""
        ...

    # ── embeddings ───────────────────────────────────────────────────────

    @abc.abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        """Return embedding vectors for the given texts."""
        ...

    # ── model listing ────────────────────────────────────────────────────

    @abc.abstractmethod
    async def list_models(self) -> list[str]:
        """Return the model IDs available from this provider."""
        ...

    # ── lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release any held resources (HTTP sessions, etc.)."""
        pass

    # ── helpers ──────────────────────────────────────────────────────────

    def _resolve_model(self, requested: Optional[str]) -> str:
        """Return the explicitly requested model, or the provider default."""
        return requested or self._config.default_model

    @property
    def is_configured(self) -> bool:
        return self._config.is_configured
