"""
Tests for the LiteLLM-backed provider clients.

These verify the provider-specific behaviour that ``LiteLLMClient`` adds on top
of LiteLLM: model-string prefixing, ``api_key``/``response_format``
passthrough, the no-embeddings guard for Groq, exception mapping into the
gateway hierarchy, and streaming chunk mapping. LiteLLM itself is mocked — no
network and no real API keys required.

Run with: uv run pytest apps/llm_gateway/tests/test_litellm_routing.py
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import litellm.exceptions as litellm_exc

from apps.llm_gateway.config import GatewaySettings, ProviderConfig
from apps.llm_gateway.exceptions import (
    AuthenticationError,
    ContentFilterError,
    ProviderAPIError,
    RateLimitError,
)
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.providers import (
    GeminiClient,
    GroqClient,
    OpenAIClient,
)
from apps.llm_gateway.types import (
    CompletionRequest,
    Message,
    Role,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _completion_resp(content="hi", model="gpt-4o", reasoning=None, tool_calls=None):
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=tool_calls,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )


def _tool_call_obj():
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="search", arguments='{"q":"x"}'),
    )


# ── model-string prefixing ───────────────────────────────────────────────────

def test_openai_prefixes_bare_model():
    client = OpenAIClient(ProviderConfig(api_key="sk"))
    assert client._litellm_model("gpt-4o") == "openai/gpt-4o"
    # already-prefixed model is left untouched
    assert client._litellm_model("openai/gpt-4o") == "openai/gpt-4o"


def test_gemini_prefix_and_strip_models():
    client = GeminiClient(ProviderConfig(api_key="AIza"))
    assert client._litellm_model("gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert client._embed_model("models/gemini-embedding-001") == "gemini/gemini-embedding-001"


def test_groq_prefix():
    client = GroqClient(ProviderConfig(api_key="gsk"))
    assert client._litellm_model("llama-3.3-70b-versatile") == "groq/llama-3.3-70b-versatile"


# ── completion: passthrough + response mapping ───────────────────────────────

@pytest.mark.asyncio
async def test_complete_calls_litellm_with_prefix_and_api_key():
    client = OpenAIClient(ProviderConfig(api_key="sk-test", default_model="gpt-4o"))
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _completion_resp(content="Hello", model="openai/gpt-4o")

    with patch("litellm.acompletion", new=fake_acompletion):
        req = CompletionRequest(
            messages=[Message(role=Role.USER, content="Hi")],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        resp = await client.complete(req)

    assert captured["model"] == "openai/gpt-4o"
    assert captured["api_key"] == "sk-test"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["temperature"] == 0.3
    assert resp.content == "Hello"
    assert resp.provider == "openai"
    assert resp.model == "openai/gpt-4o"
    assert resp.usage.total_tokens == 8


@pytest.mark.asyncio
async def test_complete_extracts_reasoning_and_tool_calls():
    client = OpenAIClient(ProviderConfig(api_key="sk"))
    resp_obj = _completion_resp(
        content=None,
        reasoning="thinking...",
        tool_calls=[_tool_call_obj()],
    )
    with patch("litellm.acompletion", new=AsyncMock(return_value=resp_obj)):
        resp = await client.complete(CompletionRequest(messages=[Message(role=Role.USER, content="x")]))

    assert resp.reasoning == "thinking..."
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "search"
    assert resp.tool_calls[0].arguments == '{"q":"x"}'


# ── embeddings ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_passes_prefixed_model():
    client = OpenAIClient(ProviderConfig(api_key="sk"))
    captured: dict = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model="openai/text-embedding-3-small",
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        )

    with patch("litellm.aembedding", new=fake_aembedding):
        resp = await client.embed(["hello"])

    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["api_key"] == "sk"
    assert resp.embeddings == [[0.1, 0.2, 0.3]]
    assert resp.provider == "openai"
    assert resp.usage.total_tokens == 4


@pytest.mark.asyncio
async def test_groq_embed_not_supported():
    client = GroqClient(ProviderConfig(api_key="gsk"))
    with pytest.raises(ProviderAPIError) as excinfo:
        await client.embed(["hello"])
    assert "embeddings" in str(excinfo.value).lower()


# ── error mapping ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_map_rate_limit_to_retryable():
    client = OpenAIClient(ProviderConfig(api_key="sk", default_model="gpt-4o"))

    def raise_rl(**_kwargs):
        raise litellm_exc.RateLimitError("slow down", llm_provider="openai", model="gpt-4o")

    with patch("litellm.acompletion", new=raise_rl):
        with pytest.raises(RateLimitError) as excinfo:
            await client.complete(CompletionRequest(messages=[Message(role=Role.USER, content="x")]))

    assert excinfo.value.retryable is True
    assert excinfo.value.provider == "openai"
    assert excinfo.value.status_code == 429


@pytest.mark.asyncio
async def test_map_auth_error_not_retryable():
    client = OpenAIClient(ProviderConfig(api_key="sk", default_model="gpt-4o"))

    def raise_auth(**_kwargs):
        raise litellm_exc.AuthenticationError("bad key", llm_provider="openai", model="gpt-4o")

    with patch("litellm.acompletion", new=raise_auth):
        with pytest.raises(AuthenticationError) as excinfo:
            await client.complete(CompletionRequest(messages=[Message(role=Role.USER, content="x")]))

    assert excinfo.value.retryable is False


@pytest.mark.asyncio
async def test_map_bad_request_content_filter():
    client = OpenAIClient(ProviderConfig(api_key="sk", default_model="gpt-4o"))

    def raise_cf(**_kwargs):
        raise litellm_exc.BadRequestError("content_filter blocked", model="gpt-4o", llm_provider="openai")

    with patch("litellm.acompletion", new=raise_cf):
        with pytest.raises(ContentFilterError):
            await client.complete(CompletionRequest(messages=[Message(role=Role.USER, content="x")]))


# ── gateway-level fallback driven by LiteLLM error mapping ───────────────────

@pytest.mark.asyncio
async def test_gateway_fallback_on_litellm_rate_limit():
    """A LiteLLM RateLimitError maps to our retryable error → gateway falls over."""
    settings = GatewaySettings(
        openai=ProviderConfig(api_key="sk-openai", default_model="gpt-4o"),
        gemini=ProviderConfig(api_key="AIza-gemini", default_model="gemini-2.5-flash"),
        groq=ProviderConfig(api_key=""),
        default_provider="openai",
    )

    async def fake_acompletion(**kwargs):
        if kwargs["model"].startswith("openai/"):
            raise litellm_exc.RateLimitError("rate limited", llm_provider="openai", model="gpt-4o")
        return _completion_resp(content="Gemini fallback!", model="gemini/gemini-2.5-flash")

    with patch("litellm.acompletion", new=fake_acompletion):
        gw = LLMGateway(settings)
        resp = await gw.complete(
            CompletionRequest(messages=[Message(role=Role.USER, content="Hi")]),
            provider="openai",
            fallback=True,
        )

    assert resp.content == "Gemini fallback!"
    assert resp.provider == "gemini"


# ── streaming ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_maps_chunks():
    client = OpenAIClient(ProviderConfig(api_key="sk", default_model="gpt-4o"))

    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="Hello", tool_calls=None, reasoning_content=None),
            finish_reason=None,
        )]),
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=" world", tool_calls=None, reasoning_content=None),
            finish_reason="stop",
        )]),
    ]

    async def fake_acompletion(**kwargs):
        assert kwargs["stream"] is True
        return _async_iter(chunks)

    collected = []
    with patch("litellm.acompletion", new=fake_acompletion):
        async for chunk in client.stream(CompletionRequest(messages=[Message(role=Role.USER, content="x")])):
            collected.append(chunk)

    assert [c.content for c in collected] == ["Hello", " world"]
    assert collected[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_gateway_stream_strips_think_tags():
    """Gateway-level ⧖ stripping still works over a LiteLLM-backed client."""
    settings = GatewaySettings(
        openai=ProviderConfig(api_key="sk", default_model="gpt-4o"),
        groq=ProviderConfig(api_key=""),
        gemini=ProviderConfig(api_key=""),
        default_provider="openai",
    )

    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="<think>secret", tool_calls=None, reasoning_content=None),
            finish_reason=None,
        )]),
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=" reasoning</think>real answer", tool_calls=None, reasoning_content=None),
            finish_reason="stop",
        )]),
    ]

    async def fake_acompletion(**_kwargs):
        return _async_iter(chunks)

    with patch("litellm.acompletion", new=fake_acompletion):
        gw = LLMGateway(settings)
        out = []
        async for chunk in gw.stream(CompletionRequest(messages=[Message(role=Role.USER, content="x")])):
            out.append(chunk)

    content = "".join(c.content for c in out)
    reasoning = "".join((c.reasoning or "") for c in out)
    assert "real answer" in content
    assert "<think>" not in content
    assert "secret reasoning" in reasoning


# ── list_models ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_models_includes_default_and_filters_prefix():
    client = OpenAIClient(ProviderConfig(api_key="sk", default_model="gpt-4o"))
    models = await client.list_models()
    # default model always present, prefixed
    assert "openai/gpt-4o" in models
    # every entry carries the openai/ prefix
    assert all(m.startswith("openai/") for m in models)


# ── close is a no-op ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_is_noop():
    client = OpenAIClient(ProviderConfig(api_key="sk"))
    await client.close()  # must not raise


# ── not-configured guard ─────────────────────────────────────────────────────

def test_not_configured_raises():
    from apps.llm_gateway.exceptions import ProviderNotConfiguredError

    with pytest.raises(ProviderNotConfiguredError):
        OpenAIClient(ProviderConfig(api_key=""))


# ── utility ──────────────────────────────────────────────────────────────────

async def _async_iter(items):
    for item in items:
        yield item