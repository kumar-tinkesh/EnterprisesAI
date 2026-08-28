"""
LLM Gateway — Unified Gateway (Router + Fallback + Factory).

This is the **single entry-point** that the rest of the platform imports.
It:
  1. Lazily initialises provider clients based on which API keys are set.
  2. Routes requests to the requested (or default) provider.
  3. Implements automatic fallback: if the primary provider fails with a
     retryable error, the gateway tries the next configured provider.
  4. Exposes a simple top-level API identical to BaseLLMClient.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from apps.llm_gateway.config import GatewaySettings
from apps.llm_gateway.exceptions import (
    LLMGatewayError,
    ProviderNotConfiguredError,
)
from apps.llm_gateway.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    Provider,
    StreamChunk,
    ReasoningStreamParser,
    extract_think_block,
)
from apps.llm_gateway.providers.base import BaseLLMClient
from apps.llm_gateway.providers.openai_client import OpenAIClient
from apps.llm_gateway.providers.groq_client import GroqClient
from apps.llm_gateway.providers.gemini_client import GeminiClient

logger = logging.getLogger("llm_gateway.gateway")


# ── Fallback ordering ────────────────────────────────────────────────────────
# When a provider fails with a retryable error, try the others in this order.
_FALLBACK_ORDER: dict[str, list[str]] = {
    "openai": ["gemini", "groq"],
    "groq": ["openai", "gemini"],
    "gemini": ["openai", "groq"],
}


class LLMGateway:
    """
    Unified entry-point for all LLM operations across the platform.
    """

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._clients: dict[str, BaseLLMClient] = {}
        self._init_clients()

    @classmethod
    def from_env(cls) -> LLMGateway:
        """Create a gateway using environment variables."""
        return cls(GatewaySettings.from_env())

    # ── public API ───────────────────────────────────────────────────────

    async def complete(
        self,
        request: CompletionRequest,
        *,
        provider: Optional[str] = None,
        fallback: bool = True,
    ) -> CompletionResponse:
        """
        Run a chat completion. Automatically separates reasoning <think> blocks
        into resp.reasoning while keeping resp.content clean.
        """
        primary = provider or self._settings.default_provider
        providers_to_try = self._build_try_order(primary, fallback)

        last_error: Optional[LLMGatewayError] = None
        for name in providers_to_try:
            client = self._clients.get(name)
            if client is None:
                continue
            try:
                logger.info("complete → %s (%s)", name, request.model or "default")
                resp = await client.complete(request)
                if resp.content:
                    clean, think_reasoning = extract_think_block(resp.content)
                    resp.content = clean
                    if think_reasoning:
                        resp.reasoning = (
                            f"{resp.reasoning}\n\n{think_reasoning}".strip()
                            if resp.reasoning
                            else think_reasoning
                        )
                return resp
            except LLMGatewayError as exc:
                last_error = exc
                if exc.retryable and fallback:
                    logger.warning(
                        "Provider %s failed (retryable), trying next: %s",
                        name,
                        exc,
                    )
                    continue
                raise

        raise last_error or ProviderNotConfiguredError(
            f"No configured provider available. Tried: {providers_to_try}"
        )

    async def stream(
        self,
        request: CompletionRequest,
        *,
        provider: Optional[str] = None,
        fallback: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream a chat completion. Intercepts <think>...</think> tags so chunk.content
        contains only clean response text while chunk.reasoning carries thinking deltas.
        """
        primary = provider or self._settings.default_provider
        providers_to_try = self._build_try_order(primary, fallback)

        last_error: Optional[LLMGatewayError] = None
        for name in providers_to_try:
            client = self._clients.get(name)
            if client is None:
                continue
            try:
                logger.info("stream → %s (%s)", name, request.model or "default")
                parser = ReasoningStreamParser()
                async for chunk in client.stream(request):
                    processed = parser.process(chunk)
                    yield processed
                return
            except LLMGatewayError as exc:
                last_error = exc
                if exc.retryable and fallback:
                    logger.warning(
                        "Provider %s stream failed (retryable), trying next: %s",
                        name,
                        exc,
                    )
                    continue
                raise

        raise last_error or ProviderNotConfiguredError(
            f"No configured provider available. Tried: {providers_to_try}"
        )

    async def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> EmbeddingResponse:
        """
        Generate embeddings.

        Defaults to OpenAI (text-embedding-3-small) or Gemini (text-embedding-004).
        Groq does not support embeddings and is skipped.
        """
        primary = provider or self._settings.embedding_provider
        # For embeddings, prefer providers that actually support them
        embed_order = [
            p for p in self._build_try_order(primary, fallback=True) if p != "groq"
        ]

        last_error: Optional[LLMGatewayError] = None
        for name in embed_order:
            client = self._clients.get(name)
            if client is None:
                continue
            try:
                logger.info("embed → %s (%s)", name, model or "default")
                return await client.embed(texts, model=model)
            except LLMGatewayError as exc:
                last_error = exc
                logger.warning("Provider %s embedding failed, trying next: %s", name, exc)
                continue

        raise last_error or ProviderNotConfiguredError(
            "No provider configured that supports embeddings."
        )

    async def list_models(self, provider: Optional[str] = None) -> dict[str, list[str]]:
        """
        List available models.  If provider is None, returns models from
        every configured provider.
        """
        result: dict[str, list[str]] = {}
        targets = [provider] if provider else list(self._clients.keys())
        for name in targets:
            client = self._clients.get(name)
            if client is None:
                continue
            try:
                result[name] = await client.list_models()
            except LLMGatewayError as exc:
                logger.warning("list_models failed for %s: %s", name, exc)
                result[name] = []
        return result

    # ── introspection ────────────────────────────────────────────────────

    @property
    def configured_providers(self) -> list[str]:
        """Return names of all providers that have valid API keys."""
        return list(self._clients.keys())

    @property
    def default_provider(self) -> str:
        return self._settings.default_provider

    def get_client(self, provider: str) -> BaseLLMClient:
        """Get the raw client for a provider (for advanced usage)."""
        client = self._clients.get(provider)
        if client is None:
            raise ProviderNotConfiguredError(
                f"Provider '{provider}' is not configured.",
                provider=provider,
            )
        return client

    # ── lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Shut down all provider HTTP sessions."""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                logger.exception("Error closing client")
        self._clients.clear()

    # ── private ──────────────────────────────────────────────────────────

    def _init_clients(self) -> None:
        """Lazily create only the clients whose API keys are present."""
        configs = {
            "openai": self._settings.openai,
            "groq": self._settings.groq,
            "gemini": self._settings.gemini,
        }
        factories = {
            "openai": OpenAIClient,
            "groq": GroqClient,
            "gemini": GeminiClient,
        }
        for name, cfg in configs.items():
            if cfg.is_configured:
                try:
                    self._clients[name] = factories[name](cfg)
                    logger.info("Provider '%s' initialised ✓", name)
                except ProviderNotConfiguredError:
                    logger.debug("Provider '%s' skipped (not configured).", name)
            else:
                logger.debug("Provider '%s' skipped (no API key).", name)

        if not self._clients:
            logger.warning(
                "⚠ No LLM providers configured. "
                "Set at least one of OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY."
            )

    def _build_try_order(self, primary: str, fallback: bool) -> list[str]:
        """Return the ordered list of providers to attempt."""
        order = [primary]
        if fallback:
            order.extend(_FALLBACK_ORDER.get(primary, []))
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for p in order:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique
