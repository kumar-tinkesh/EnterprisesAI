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

import copy
import hashlib
import json
import logging
import time
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
        # In-memory TTL response cache: key -> (last_stored_ts, response).
        self._cache: dict[str, tuple[float, CompletionResponse]] = {}
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

        # Response cache (opt-in via GatewaySettings.enable_cache).
        cache_key = self._cache_key(primary, request)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("complete → cache HIT (%s)", primary)
            return cached

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
                self._cache_set(cache_key, resp)
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

    def _cache_key(self, provider: str, request: CompletionRequest) -> str:
        """Build a deterministic cache key from the provider + request params."""
        payload: dict[str, object] = {
            "provider": provider,
            "model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
            "stop": request.stop,
            "messages": [m.to_dict() for m in request.messages],
            "tools": [t.to_dict() for t in (request.tools or [])],
            "tool_choice": request.tool_choice,
            "response_format": request.response_format,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        return f"{provider}:{digest}"

    def _cache_get(self, key: str) -> Optional[CompletionResponse]:
        """Return a fresh cached copy, or None on miss / expiry (cache off-safe)."""
        if not self._settings.enable_cache:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, resp = entry
        if time.monotonic() - stored_at > self._settings.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        # Return a deep copy so callers can never mutate the cached object.
        return copy.deepcopy(resp)

    def _cache_set(self, key: str, resp: CompletionResponse) -> None:
        if not self._settings.enable_cache:
            return
        self._cache[key] = (time.monotonic(), copy.deepcopy(resp))

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
