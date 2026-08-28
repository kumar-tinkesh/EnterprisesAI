"""
LLM Gateway — Google Gemini provider client.

Uses Google's OpenAI-compatible endpoint
(``https://generativelanguage.googleapis.com/v1beta/openai``)
so we can drive it with the standard ``openai`` async SDK — same
pattern as the Groq client.

Alternatively, if the native ``google-genai`` SDK is needed for
advanced features (grounding, code execution, etc.), a second class
can be added later without changing the gateway interface.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import httpx
import openai
from openai import AsyncOpenAI

from apps.llm_gateway.config import ProviderConfig
from apps.llm_gateway.exceptions import (
    AuthenticationError,
    ContentFilterError,
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

logger = logging.getLogger("llm_gateway.gemini")


class GeminiClient(BaseLLMClient):
    """
    Async client for Google Gemini via the OpenAI-compatible gateway.

    Default model: ``gemini-2.5-flash``
    """

    PROVIDER_NAME = "gemini"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.is_configured:
            raise ProviderNotConfiguredError(
                "GEMINI_API_KEY is not set.", provider=self.PROVIDER_NAME
            )
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url
            or "https://generativelanguage.googleapis.com/v1beta/openai",
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

        reasoning = getattr(choice.message, "reasoning_content", None) or getattr(
            choice.message, "reasoning", None
        )

        return CompletionResponse(
            content=choice.message.content,
            reasoning=reasoning,
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

    # ── embeddings ───────────────────────────────────────────────────────

    async def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        target_model = model or self._config.default_embedding_model or "gemini-embedding-001"
        clean_model_name = target_model.replace("models/", "")

        vectors: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=float(self._config.timeout_seconds)) as client:
                for text in texts:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{clean_model_name}:embedContent?key={self._config.api_key}"
                    )
                    res = await client.post(
                        url,
                        json={"content": {"parts": [{"text": text}]}},
                    )
                    if res.status_code != 200:
                        raise ProviderAPIError(
                            f"Gemini embedding error ({res.status_code}): {res.text}",
                            provider=self.PROVIDER_NAME,
                        )
                    data = res.json()
                    embedding_vals = data.get("embedding", {}).get("values", [])
                    vectors.append(embedding_vals)
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise ProviderAPIError(
                f"Gemini embedding request failed: {exc}", provider=self.PROVIDER_NAME
            ) from exc

        return EmbeddingResponse(
            embeddings=vectors,
            model=clean_model_name,
            provider=self.PROVIDER_NAME,
            usage=TokenUsage(),
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
        if "context_length" in str(exc).lower() or "token" in str(exc).lower():
            return TokenLimitExceededError(str(exc), **base)
        if "safety" in str(exc).lower() or "blocked" in str(exc).lower():
            return ContentFilterError(str(exc), **base)
        return ProviderAPIError(str(exc), **base)
