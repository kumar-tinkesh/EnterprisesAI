"""
Unit & Integration Tests for LLM Gateway (apps/llm_gateway).
Run with: uv run pytest apps/llm_gateway/tests
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from apps.llm_gateway.config import GatewaySettings, ProviderConfig
from apps.llm_gateway.exceptions import (
    RateLimitError,
)
from apps.llm_gateway.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingResponse,
    Message,
    Role,
    TokenUsage,
)
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.api import app


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env_settings():
    return GatewaySettings(
        openai=ProviderConfig(api_key="sk-openai-mock", default_model="gpt-4.1"),
        groq=ProviderConfig(api_key="gsk-groq-mock", default_model="llama-3.3-70b-versatile"),
        gemini=ProviderConfig(api_key="AIza-gemini-mock", default_model="gemini-2.5-flash"),
        default_provider="openai",
        embedding_provider="openai",
    )


# ── Configuration Tests ──────────────────────────────────────────────────────

def test_gateway_settings_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_GATEWAY_DEFAULT_PROVIDER", "groq")

    settings = GatewaySettings.from_env()

    assert settings.openai.api_key == "test-openai-key"
    assert settings.groq.api_key == "test-groq-key"
    assert settings.default_provider == "groq"
    assert settings.gemini.is_configured is False


# ── Gateway Routing & Fallback Tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_gateway_init_configured_providers(mock_env_settings):
    with patch("apps.llm_gateway.gateway.OpenAIClient"), \
         patch("apps.llm_gateway.gateway.GroqClient"), \
         patch("apps.llm_gateway.gateway.GeminiClient"):
        
        gw = LLMGateway(mock_env_settings)
        assert set(gw.configured_providers) == {"openai", "groq", "gemini"}
        assert gw.default_provider == "openai"


@pytest.mark.asyncio
async def test_llm_gateway_complete_primary_success(mock_env_settings):
    mock_openai = AsyncMock()
    mock_openai.complete.return_value = CompletionResponse(
        content="Hello from OpenAI!",
        model="gpt-4o",
        provider="openai",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )

    with patch("apps.llm_gateway.gateway.OpenAIClient", return_value=mock_openai), \
         patch("apps.llm_gateway.gateway.GroqClient"), \
         patch("apps.llm_gateway.gateway.GeminiClient"):

        gw = LLMGateway(mock_env_settings)
        req = CompletionRequest(messages=[Message(role=Role.USER, content="Hi")])
        resp = await gw.complete(req)

        assert resp.content == "Hello from OpenAI!"
        assert resp.provider == "openai"
        mock_openai.complete.assert_called_once()


@pytest.mark.asyncio
async def test_llm_gateway_fallback_on_rate_limit(mock_env_settings):
    mock_openai = AsyncMock()
    mock_openai.complete.side_effect = RateLimitError("Rate limit hit", provider="openai")

    mock_gemini = AsyncMock()
    mock_gemini.complete.return_value = CompletionResponse(
        content="Hello from Gemini fallback!",
        model="gemini-2.5-flash",
        provider="gemini",
    )

    with patch("apps.llm_gateway.gateway.OpenAIClient", return_value=mock_openai), \
         patch("apps.llm_gateway.gateway.GroqClient"), \
         patch("apps.llm_gateway.gateway.GeminiClient", return_value=mock_gemini):

        gw = LLMGateway(mock_env_settings)
        req = CompletionRequest(messages=[Message(role=Role.USER, content="Hi")])
        resp = await gw.complete(req, provider="openai", fallback=True)

        assert resp.content == "Hello from Gemini fallback!"
        assert resp.provider == "gemini"
        assert mock_openai.complete.call_count == 1
        assert mock_gemini.complete.call_count == 1


@pytest.mark.asyncio
async def test_llm_gateway_embeddings_skip_groq(mock_env_settings):
    mock_openai = AsyncMock()
    mock_openai.embed.return_value = EmbeddingResponse(
        embeddings=[[0.1, 0.2, 0.3]],
        model="text-embedding-3-small",
        provider="openai",
    )

    with patch("apps.llm_gateway.gateway.OpenAIClient", return_value=mock_openai), \
         patch("apps.llm_gateway.gateway.GroqClient"), \
         patch("apps.llm_gateway.gateway.GeminiClient"):

        gw = LLMGateway(mock_env_settings)
        resp = await gw.embed(["test query"])

        assert len(resp.embeddings) == 1
        assert resp.provider == "openai"


# ── FastAPI Endpoint Tests ────────────────────────────────────────────────────

def test_api_health_endpoint():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] == "ok"


def test_api_chat_completions_mocked():
    mock_resp = CompletionResponse(
        content="API test response",
        model="gpt-4o",
        provider="openai",
        usage=TokenUsage(prompt_tokens=5, completion_tokens=4, total_tokens=9),
    )

    with patch("apps.llm_gateway.api.get_gateway") as mock_get_gw:
        mock_gw = AsyncMock()
        mock_gw.complete.return_value = mock_resp
        mock_get_gw.return_value = mock_gw

        with TestClient(app) as client:
            res = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello HTTP"}],
                    "temperature": 0.5,
                },
            )
            assert res.status_code == 200
            json_body = res.json()
            assert json_body["object"] == "chat.completion"
            assert json_body["choices"][0]["message"]["content"] == "API test response"
