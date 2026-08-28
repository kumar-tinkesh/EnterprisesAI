"""
LLM Gateway — Groq provider client.

Groq exposes an OpenAI-compatible REST API, so we re-use the ``openai``
async SDK pointed at Groq's base URL.  The only differences are:
  • different base_url (https://api.groq.com/openai/v1)
  • different default models (LLaMA, Mixtral, Gemma families)
  • no embeddings endpoint (Groq does not serve embeddings as of 2025-Q4)
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import openai
from openai import AsyncOpenAI

from apps.llm_gateway.config import ProviderConfig
from apps.llm_gateway.exceptions import (
    AuthenticationError,
    ModelNotFoundError,
    ProviderAPIError,
    ProviderNotConfiguredError,
    RateLimitError,
    TokenLimitExceededError,
)
from apps.llm_gateway.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from apps.llm_gateway.providers.base import BaseLLMClient

logger = logging.getLogger("llm_gateway.groq")


class GroqClient(BaseLLMClient):
    """
    Async client for Groq (ultra-low-latency inference).

    Default model: ``llama-3.3-70b-versatile``
    """

    PROVIDER_NAME = "groq"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.is_configured:
            raise ProviderNotConfiguredError(
                "GROQ_API_KEY is not set.", provider=self.PROVIDER_NAME
            )
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url or "https://api.groq.com/openai/v1",
            max_retries=config.max_retries,
            timeout=float(config.timeout_seconds),
        )

    # ── chat completion ──────────────────────────────────────────────────

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = self._resolve_model(request.model)
        kwargs = self._build_kwargs(request, model)
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            raise self._map_error(exc, model) from exc

        choice = resp.choices[0]
        tool_calls = self._extract_tool_calls(choice)
        usage = self._extract_usage(resp)

        return CompletionResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            usage=usage,
            model=resp.model,
            provider=self.PROVIDER_NAME,
            finish_reason=choice.finish_reason,
            raw=resp,
        )

    # ── streaming ────────────────────────────────────────────────────────

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        model = self._resolve_model(request.model)
        kwargs = self._build_kwargs(request, model)
        kwargs["stream"] = True
        try:
            async_stream = await self._client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            raise self._map_error(exc, model) from exc

        async for chunk in async_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            tc: list[ToolCall] = []
            if delta.tool_calls:
                for t in delta.tool_calls:
                    if t.function:
                        tc.append(
                            ToolCall(
                                id=t.id or "",
                                name=t.function.name or "",
                                arguments=t.function.arguments or "",
                            )
                        )
            yield StreamChunk(
                content=delta.content or "",
                finish_reason=chunk.choices[0].finish_reason,
                tool_calls=tc,
            )

    # ── embeddings (not supported by Groq) ───────────────────────────────

    async def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        raise ProviderAPIError(
            "Groq does not provide an embeddings API. "
            "Use OpenAI or Gemini for embeddings.",
            provider=self.PROVIDER_NAME,
        )

    # ── model listing ────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        try:
            result = await self._client.models.list()
            return sorted([m.id for m in result.data])
        except openai.APIError as exc:
            raise self._map_error(exc, "") from exc

    # ── lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.close()

    # ── private helpers ──────────────────────────────────────────────────

    def _build_kwargs(self, request: CompletionRequest, model: str) -> dict:
        kwargs: dict = {
            "model": model,
            "messages": [m.to_dict() for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.stop:
            kwargs["stop"] = request.stop
        if request.tools:
            kwargs["tools"] = [t.to_dict() for t in request.tools]
        if request.tool_choice is not None:
            kwargs["tool_choice"] = request.tool_choice
        if request.response_format:
            kwargs["response_format"] = request.response_format
        return kwargs

    @staticmethod
    def _extract_tool_calls(choice) -> list[ToolCall]:
        if not choice.message.tool_calls:
            return []
        return [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in choice.message.tool_calls
        ]

    @staticmethod
    def _extract_usage(resp) -> TokenUsage:
        if not resp.usage:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
        )

    def _map_error(self, exc: openai.APIError, model: str) -> ProviderAPIError:
        status = getattr(exc, "status_code", None)
        base = dict(provider=self.PROVIDER_NAME, model=model, status_code=status)
        if status == 401 or status == 403:
            return AuthenticationError(str(exc), **base)
        if status == 429:
            return RateLimitError(str(exc), **base)
        if status == 404:
            return ModelNotFoundError(str(exc), **base)
        if "context_length" in str(exc).lower():
            return TokenLimitExceededError(str(exc), **base)
        return ProviderAPIError(str(exc), **base)
