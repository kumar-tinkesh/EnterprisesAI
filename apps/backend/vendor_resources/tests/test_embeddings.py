"""Unit tests for the embedding helpers (cosine + best-effort embed_text)."""
from __future__ import annotations

import pytest

from apps.llm_gateway.exceptions import ProviderNotConfiguredError

from vendor_resources.services import embeddings


def test_cosine_identical_vectors():
    assert embeddings.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert embeddings.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_mismatched_length_is_zero():
    assert embeddings.cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_cosine_zero_vector_is_zero():
    assert embeddings.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_empty_is_zero():
    assert embeddings.cosine_similarity([], []) == 0.0


@pytest.mark.asyncio
async def test_embed_text_returns_none_when_no_provider(monkeypatch):
    class _Boom:
        async def embed(self, *_a, **_kw):
            raise ProviderNotConfiguredError("no keys")

    monkeypatch.setattr(embeddings, "get_gateway", lambda: _Boom())
    assert await embeddings.embed_text("hello") is None


@pytest.mark.asyncio
async def test_embed_text_empty_input_returns_none():
    assert await embeddings.embed_text("") is None


@pytest.mark.asyncio
async def test_embed_text_returns_vector_and_model(monkeypatch):
    from apps.llm_gateway.types import EmbeddingResponse, TokenUsage

    class _Ok:
        async def embed(self, texts, *, model=None, provider=None):
            return EmbeddingResponse(
                embeddings=[[0.1, 0.2, 0.3]],
                model="text-embedding-3-small",
                provider="openai",
                usage=TokenUsage(prompt_tokens=1, total_tokens=1),
            )

    monkeypatch.setattr(embeddings, "get_gateway", lambda: _Ok())
    result = await embeddings.embed_text("hello")
    assert result is not None
    vec, model = result
    assert vec == [0.1, 0.2, 0.3]
    assert model == "text-embedding-3-small"