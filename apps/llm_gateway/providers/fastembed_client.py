"""
fastembed — the platform's default embedding provider.

Runs ``BAAI/bge-small-en-v1.5`` (override with ``FASTEMBED_MODEL``) on the CPU
through fastembed's ONNX runtime: no API key, no network after the one-time
model download (the backend image bakes the model in). ``fastembed`` is
imported lazily, so a process without it (the slim gateway container) just
reports "not configured".
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any, Optional

from apps.llm_gateway.exceptions import ProviderNotConfiguredError
from apps.llm_gateway.types import EmbeddingResponse

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"


def fastembed_model() -> str:
    return os.getenv("FASTEMBED_MODEL", "").strip() or DEFAULT_FASTEMBED_MODEL


@lru_cache
def load_text_embedding(model_name: str) -> Any:
    """One loaded model per process, shared by every caller (MCP catalog,
    knowledge base, guardrails) so the ONNX weights sit in memory once."""
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise ProviderNotConfiguredError(
            "The 'fastembed' package isn't installed in this process."
        ) from exc
    return TextEmbedding(model_name=model_name)


class FastEmbedClient:
    PROVIDER_NAME = "fastembed"

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or fastembed_model()

    async def embed(self, texts: list[str], *, model: Optional[str] = None) -> EmbeddingResponse:
        name = model or self.model_name
        encoder = load_text_embedding(name)
        vectors = await asyncio.to_thread(lambda: [v.tolist() for v in encoder.embed(texts)])
        return EmbeddingResponse(embeddings=vectors, model=name, provider=self.PROVIDER_NAME)


__all__ = ["FastEmbedClient", "fastembed_model", "load_text_embedding"]
