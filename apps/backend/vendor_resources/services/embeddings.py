"""Embedding helpers for the Vendor Resources subsystem.

A thin, best-effort wrapper around the shared LLM gateway's ``embed()`` API.
The backend keeps its own process-wide gateway instance
(:func:`get_gateway`) because the gateway package does not expose a singleton
for external consumers (the one in ``apps/llm_gateway/api.py`` is only valid
inside that service's own lifespan).

All embedding calls are **best-effort**: if no provider is configured or the
call fails, ``None`` is returned so callers (e.g. tool creation) can degrade
gracefully — the catalog's semantic matcher then simply skips unembedded tools.
"""
from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Optional

from apps.llm_gateway.exceptions import LLMGatewayError
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.types import EmbeddingResponse

logger = logging.getLogger("vendor_resources.embeddings")


@lru_cache
def get_gateway() -> LLMGateway:
    """Return a cached backend-wide :class:`LLMGateway` built from env."""
    return LLMGateway.from_env()


async def embed_text(
    text: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[tuple[list[float], str]]:
    """Embed ``text`` via the gateway.

    Returns ``(vector, model_used)`` on success, or ``None`` if no provider is
    configured or the call fails. Never raises — callers rely on graceful
    degradation.
    """
    if not text:
        return None
    try:
        gw = get_gateway()
        resp: EmbeddingResponse = await gw.embed([text], provider=provider, model=model)
    except LLMGatewayError as exc:
        logger.warning("embed_text failed (degrading): %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("embed_text unexpected error (degrading): %s", exc)
        return None

    if not resp.embeddings:
        return None
    return list(resp.embeddings[0]), resp.model or (model or "")


async def embed_tool_text(tool) -> Optional[tuple[list[float], str]]:
    """Embed a tool's searchable text (``name`` + ``description``)."""
    return await embed_text(f"{tool.name}\n{tool.description}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors.

    Returns ``0.0`` on length mismatch or zero-magnitude vectors (so mismatched
    embeddings are ranked neutrally rather than erroring).
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)