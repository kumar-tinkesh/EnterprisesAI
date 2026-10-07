"""Pluggable embedding backends for knowledge chunks.

Both return plain ``list[list[float]]`` so the rest of the knowledge code (and
the JSON ``embedding`` column) never depends on which backend is active.
Selected via ``KNOWLEDGE_EMBEDDING_BACKEND``:

* ``fastembed`` (default) — local ONNX model, no API key, works offline. The
  model downloads once and is cached (``FASTEMBED_CACHE_PATH`` in Docker).
* ``gateway`` — the LLM gateway's configured embedding provider (the same
  path ``vendor.services.embedding`` uses for MCP tools).

``count_tokens`` is synchronous (chunking calls it many times); ``embed_texts``
is async so the gateway backend can await its HTTP call and the local model
runs in a worker thread instead of blocking the event loop.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from functools import lru_cache

from knowledge.config import get_knowledge_settings

# Embedding a large document's chunks in one call spikes peak memory (batched
# inference buffers scale with input count); small batches keep it flat.
EMBED_BATCH_SIZE = 24


class Embedder(ABC):
    model_name: str
    max_input_tokens: int

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens with this backend's tokenizer (or a safe estimate)."""

    @abstractmethod
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + EMBED_BATCH_SIZE]))
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding backend returned an unexpected vector count.")
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]


class FastEmbedEmbedder(Embedder):
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.model_name = model_name
        self.max_input_tokens = 512

    def count_tokens(self, text: str) -> int:
        # The BGE tokenizer ships in the same bundle as the ONNX model. It
        # truncates at 512, which is enough here: chunking subdivides any text
        # above its (much smaller) unit limit.
        return len(self._model.model.tokenizer.encode(text).ids)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_sync, texts)


class GatewayEmbedder(Embedder):
    """Embeddings from the LLM gateway (OpenAI / Gemini / Azure …).

    The gateway exposes no tokenizer, so ``count_tokens`` is a conservative
    estimate (~3 characters per token) — it only steers chunk sizes, and the
    provider limits (8k tokens) sit far above the chunk targets.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.max_input_tokens = 8192

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        from vendor.services.llm_gateway_client import get_gateway

        resp = await get_gateway().embed(texts, model=self.model_name or None)
        if resp.model and not self.model_name:
            self.model_name = resp.model
        return [list(vec) for vec in resp.embeddings]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_knowledge_settings()
    backend = settings.KNOWLEDGE_EMBEDDING_BACKEND.lower()
    if backend == "fastembed":
        return FastEmbedEmbedder(settings.KNOWLEDGE_EMBEDDING_MODEL_FASTEMBED)
    if backend == "gateway":
        return GatewayEmbedder(settings.KNOWLEDGE_EMBEDDING_MODEL_GATEWAY)
    raise ValueError(
        f"Unknown KNOWLEDGE_EMBEDDING_BACKEND '{settings.KNOWLEDGE_EMBEDDING_BACKEND}'. "
        "Use 'fastembed' or 'gateway'."
    )


__all__ = ["Embedder", "FastEmbedEmbedder", "GatewayEmbedder", "get_embedder"]
