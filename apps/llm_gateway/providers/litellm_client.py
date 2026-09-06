"""
LLM Gateway — Shared LiteLLM-backed provider client.

LiteLLM (https://github.com/BerriAI/litellm) is the single routing layer for
*every* upstream LLM provider used by the platform. It exposes a uniform
``acompletion`` / ``aembedding`` async API and normalises OpenAI-compatible
request/response shapes across providers (OpenAI, Groq, Gemini, …).

The concrete provider clients (``OpenAIClient``, ``GroqClient``,
``GeminiClient``) are thin subclasses of :class:`LiteLLMClient` that only
declare the provider name, the LiteLLM model-string prefix, default models and
whether embeddings are supported. All actual HTTP work is delegated to LiteLLM,
so there is no per-provider SDK client to construct or close.

The public contract (``complete`` / ``stream`` / ``embed`` / ``list_models`` /
``close``) and the shared gateway types (``CompletionResponse``,
``StreamChunk``, ``EmbeddingResponse``) are unchanged — the gateway's routing,
fallback, caching and ``<think>`` reasoning extraction all keep working
unchanged on top of this client.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

import litellm
import litellm.exceptions as _litellm_exc

from apps.llm_gateway.config import ProviderConfig
from apps.llm_gateway.exceptions import (
    AuthenticationError,
    ContentFilterError,
    LLMGatewayError,
    ModelNotFoundError,
    ProviderAPIError,
    ProviderNotConfiguredError,
    RateLimitError,
    TokenLimitExceededError,
)
from apps.llm_gateway.providers.base import BaseLLMClient
from apps.llm_gateway.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)

# LiteLLM is chatty by default; keep our logs readable.
litellm.suppress_debug_logging = True

logger = logging.getLogger("llm_gateway.litellm")


class LiteLLMClient(BaseLLMClient):
    """
    Base implementation backed by LiteLLM.

    Subclasses set:
      * ``PROVIDER_NAME``      — e.g. ``"openai"``
      * ``_PREFIX``            — LiteLLM model prefix, e.g. ``"openai/"``
      * ``_DEFAULT_EMBED_MODEL`` — fallback embedding model (provider-specific)
      * ``EMBEDDINGS_SUPPORTED`` — whether the provider serves embeddings
      * ``_PASS_API_BASE``     — whether to forward ``base_url`` to LiteLLM
        (False for providers whose configured ``base_url`` is an
        OpenAI-compat endpoint that conflicts with LiteLLM's native routing,
        e.g. Gemini).
    """

    PROVIDER_NAME: str = "litellm"
    _PREFIX: str = ""
    _DEFAULT_EMBED_MODEL: str = ""
    EMBEDDINGS_SUPPORTED: bool = True
    _PASS_API_BASE: bool = True

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.is_configured:
            raise ProviderNotConfiguredError(
                f"{self.PROVIDER_NAME.upper()}_API_KEY is not set.",
                provider=self.PROVIDER_NAME,
            )

    # ── chat completion ──────────────────────────────────────────────────

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        bare = self._resolve_model(request.model)
        model = self._litellm_model(bare)
        kwargs = self._build_kwargs(request, model)
        try:
            resp = await litellm.acompletion(**kwargs)
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise self._map_litellm_error(exc, model) from exc

        choices = getattr(resp, "choices", None) or []
        if not choices:
            return CompletionResponse(
                content=None,
                model=getattr(resp, "model", model),
                provider=self.PROVIDER_NAME,
                raw=resp,
            )
        choice = choices[0]
        msg = getattr(choice, "message", None)
        reasoning = (
            getattr(msg, "reasoning_content", None)
            or getattr(msg, "reasoning", None)
        ) if msg is not None else None

        return CompletionResponse(
            content=getattr(msg, "content", None) if msg is not None else None,
            reasoning=reasoning,
            tool_calls=self._extract_tool_calls(msg),
            usage=self._extract_usage(resp),
            model=getattr(resp, "model", model),
            provider=self.PROVIDER_NAME,
            finish_reason=getattr(choice, "finish_reason", None),
            raw=resp,
        )

    # ── streaming ────────────────────────────────────────────────────────

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        bare = self._resolve_model(request.model)
        model = self._litellm_model(bare)
        kwargs = self._build_kwargs(request, model)
        kwargs["stream"] = True
        try:
            async_stream = await litellm.acompletion(**kwargs)
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise self._map_litellm_error(exc, model) from exc

        try:
            async for chunk in async_stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                tc: list[ToolCall] = []
                if delta is not None:
                    for t in (getattr(delta, "tool_calls", None) or []):
                        fn = getattr(t, "function", None)
                        if fn is None:
                            continue
                        tc.append(
                            ToolCall(
                                id=getattr(t, "id", "") or "",
                                name=getattr(fn, "name", "") or "",
                                arguments=getattr(fn, "arguments", "") or "",
                            )
                        )
                yield StreamChunk(
                    content=(getattr(delta, "content", None) or "") if delta is not None else "",
                    reasoning=getattr(delta, "reasoning_content", None) if delta is not None else None,
                    finish_reason=getattr(choices[0], "finish_reason", None),
                    tool_calls=tc,
                )
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise self._map_litellm_error(exc, model) from exc

    # ── embeddings ───────────────────────────────────────────────────────

    async def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        if not self.EMBEDDINGS_SUPPORTED:
            raise ProviderAPIError(
                f"{self.PROVIDER_NAME.title()} does not provide an embeddings API. "
                "Use OpenAI or Gemini for embeddings.",
                provider=self.PROVIDER_NAME,
            )

        embed_model = self._embed_model(
            model
            or self._config.default_embedding_model
            or self._DEFAULT_EMBED_MODEL
        )
        kwargs: dict[str, Any] = {
            "model": embed_model,
            "input": texts,
            **self._provider_kwargs(),
        }
        try:
            resp = await litellm.aembedding(**kwargs)
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise self._map_litellm_error(exc, embed_model) from exc

        # LiteLLM exposes embeddings under either ``data`` (OpenAI shape) or
        # ``results`` (its own shape) depending on the provider.
        data = getattr(resp, "data", None)
        if data is None:
            data = getattr(resp, "results", None) or []
        vectors = [list(getattr(item, "embedding", []) or []) for item in data]

        usage = getattr(resp, "usage", None)
        return EmbeddingResponse(
            embeddings=vectors,
            model=getattr(resp, "model", embed_model),
            provider=self.PROVIDER_NAME,
            usage=TokenUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0 if usage else 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0 if usage else 0,
            ),
        )

    # ── model listing ────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        """Return model IDs known to LiteLLM for this provider.

        LiteLLM's ``model_cost`` is a static catalogue rather than a live
        ``/models`` call, so this is best-effort; the configured default model
        is always included. A live ``/models`` lookup can be added later.
        """
        try:
            cost = getattr(litellm, "model_cost", {}) or {}
            models = sorted(k for k in cost.keys() if k.startswith(self._PREFIX))
        except Exception:  # pragma: no cover - defensive
            models = []

        default = self._config.default_model
        if default:
            default_prefixed = self._litellm_model(default)
            if default_prefixed not in models:
                models = sorted({default_prefixed, *models})
        return models

    # ── lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """No per-instance resources — LiteLLM manages its own HTTP pool."""
        pass

    # ── private helpers ──────────────────────────────────────────────────

    def _litellm_model(self, bare: str) -> str:
        """Prefix a bare model id with the provider prefix unless already
        prefixed. Azure OpenAI (see ``ProviderConfig.is_azure``) routes by
        *deployment name* under an ``azure/`` prefix instead — never the
        plain ``openai/`` prefix, which hits Azure's endpoint with the wrong
        URL shape and 404s.
        """
        if not bare:
            return bare
        if "/" in bare:
            return bare
        if self._config.is_azure:
            return f"azure/{self._config.azure_chat_deployment or bare}"
        return f"{self._PREFIX}{bare}"

    def _embed_model(self, bare: str) -> str:
        """Same as ``_litellm_model`` but for embeddings — its own Azure
        deployment (may differ from the chat deployment) and strips a
        leading ``models/`` (Gemini)."""
        if bare and bare.startswith("models/"):
            bare = bare[len("models/"):]
        if not bare:
            return bare
        if "/" in bare:
            return bare
        if self._config.is_azure:
            return f"azure/{self._config.azure_embedding_deployment or bare}"
        return f"{self._PREFIX}{bare}"

    def _provider_kwargs(self) -> dict[str, Any]:
        """LiteLLM auth / endpoint kwargs passed to every call."""
        kwargs: dict[str, Any] = {"api_key": self._config.api_key}
        if self._PASS_API_BASE and self._config.base_url:
            kwargs["api_base"] = self._config.base_url
        if self._config.is_azure and self._config.api_version:
            # Azure OpenAI requires an api-version query param; plain
            # OpenAI-compatible endpoints don't take this kwarg at all.
            kwargs["api_version"] = self._config.api_version
        if self._config.organization:
            kwargs["organization"] = self._config.organization
        if self._config.timeout_seconds:
            kwargs["timeout"] = float(self._config.timeout_seconds)
        if self._config.max_retries is not None:
            kwargs["num_retries"] = self._config.max_retries
        return kwargs

    def _build_kwargs(self, request: CompletionRequest, model: str) -> dict:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            **self._provider_kwargs(),
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
    def _extract_tool_calls(msg) -> list[ToolCall]:
        if msg is None:
            return []
        tcs = getattr(msg, "tool_calls", None) or []
        out: list[ToolCall] = []
        for tc in tcs:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            out.append(
                ToolCall(
                    id=getattr(tc, "id", "") or "",
                    name=getattr(fn, "name", "") or "",
                    arguments=getattr(fn, "arguments", "") or "",
                )
            )
        return out

    @staticmethod
    def _extract_usage(resp) -> TokenUsage:
        usage = getattr(resp, "usage", None)
        if not usage:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )

    def _map_litellm_error(self, exc: Exception, model: str) -> ProviderAPIError:
        """Map a LiteLLM exception into the gateway's exception hierarchy."""
        if isinstance(exc, LLMGatewayError):
            return exc  # already one of ours; never double-wrap
        base = dict(
            provider=self.PROVIDER_NAME,
            model=model,
            status_code=getattr(exc, "status_code", None),
        )
        message = str(exc)

        if isinstance(exc, _litellm_exc.AuthenticationError):
            return AuthenticationError(message, **base)
        if isinstance(exc, _litellm_exc.RateLimitError):
            return RateLimitError(message, **base)
        if isinstance(exc, _litellm_exc.NotFoundError):
            return ModelNotFoundError(message, **base)
        if isinstance(exc, _litellm_exc.ContextWindowExceededError):
            return TokenLimitExceededError(message, **base)
        if isinstance(exc, _litellm_exc.BadRequestError):
            low = message.lower()
            if "content_filter" in low or "safety" in low or "blocked" in low:
                return ContentFilterError(message, **base)
            return ProviderAPIError(message, **base)
        if isinstance(
            exc,
            (
                _litellm_exc.APIConnectionError,
                _litellm_exc.Timeout,
                _litellm_exc.ServiceUnavailableError,
            ),
        ):
            # Retryable so the gateway's fallback ordering kicks in.
            return ProviderAPIError(message, retryable=True, **base)
        return ProviderAPIError(message, **base)