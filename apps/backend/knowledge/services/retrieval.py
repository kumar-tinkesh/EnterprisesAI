"""Hybrid retrieval over one knowledge base: vector + BM25 -> RRF -> rerank -> MMR.

1. Cosine similarity (meaning) and BM25 (exact terms: IDs, acronyms, names)
   rank the knowledge base's chunks independently.
2. Reciprocal Rank Fusion merges the two rankings by rank position, so the
   incomparable score scales never have to be mixed.
3. A local cross-encoder (fastembed ONNX, CPU) scores each query+chunk pair
   of the fused shortlist; its score is blended with the fused rank score.
   Best-effort: if the model can't load, the fused order is used as is.
4. MMR picks the final top-k, trading relevance against similarity to what's
   already picked, so near-duplicate chunks don't crowd out everything else.

Unlike the Marketplace version (pgvector KNN + PostgreSQL full-text search),
both candidate signals are computed in Python over the knowledge base's
chunks, so this works on SQLite as well as PostgreSQL. That loads one
knowledge base's chunks per query — fine for thousands of chunks; a very large
corpus would want a native vector index instead.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from functools import lru_cache

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge.config import get_knowledge_settings
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services.embeddings import get_embedder

logger = logging.getLogger("knowledge.retrieval")

_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an the this that these those is are was were be been being "
    "i you he she it we they my your his her its our their "
    "in on at for to of and or but if then else so as by with without "
    "from into onto up down out about over under "
    "do does did will would shall should can could may might must "
    "not no nor only own same than too very just what which who how".split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS]


@lru_cache
def _get_reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=_RERANK_MODEL)


def _rerank_scores(query: str, texts: list[str]) -> list[float] | None:
    """Sigmoid-normalised cross-encoder scores, or None if the model is unavailable."""
    try:
        raw = list(_get_reranker().rerank(query, texts))
    except Exception:
        logger.warning("knowledge rerank unavailable, using fused rank order", exc_info=True)
        return None
    return [float(1.0 / (1.0 + np.exp(-float(s)))) for s in raw]


def _vector_order(query_vec: list[float], embeddings: list[list[float] | None]) -> list[int]:
    dim = len(query_vec)
    idx = [i for i, e in enumerate(embeddings) if e and len(e) == dim]
    if not idx:
        return []
    matrix = np.asarray([embeddings[i] for i in idx], dtype=np.float32)
    q = np.asarray(query_vec, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
    norms[norms == 0] = 1.0
    sims = matrix @ q / norms
    return [idx[i] for i in np.argsort(-sims)]


def _bm25_order(query: str, texts: list[str], k1: float = 1.5, b: float = 0.75) -> list[int]:
    """Chunk indices with any keyword overlap, best BM25 score first.

    Lucene's BM25 idf, ``ln(1 + (N - n + 0.5) / (n + 0.5))``, is always
    positive. rank_bm25's Okapi idf is not: in a small knowledge base (two
    chunks, a term in one of them) it is exactly 0 for every term and the
    keyword signal silently disappears.
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    docs = [_tokenize(t) for t in texts]
    n_docs = len(docs)
    avg_len = (sum(len(d) for d in docs) / n_docs) or 1.0
    df: dict[str, int] = {}
    for d in docs:
        for term in query_tokens.intersection(d):
            df[term] = df.get(term, 0) + 1
    if not df:
        return []
    idf = {t: math.log(1 + (n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    scores: dict[int, float] = {}
    for i, d in enumerate(docs):
        tf: dict[str, int] = {}
        for term in d:
            if term in idf:
                tf[term] = tf.get(term, 0) + 1
        if tf:
            norm = k1 * (1 - b + b * len(d) / avg_len)
            scores[i] = sum(idf[t] * f * (k1 + 1) / (f + norm) for t, f in tf.items())
    return sorted(scores, key=scores.get, reverse=True)


def _mmr_select(pool: list[dict], vectors: list[np.ndarray | None], k: int, lambda_mult: float = 0.7) -> list[int]:
    if len(pool) <= k:
        return list(range(len(pool)))

    def sim(i: int, j: int) -> float:
        a, b = vectors[i], vectors[j]
        if a is None or b is None:
            return 0.0
        denom = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
        return float(np.dot(a, b) / denom)

    selected: list[int] = []
    remaining = list(range(len(pool)))
    while remaining and len(selected) < k:
        best, best_score = remaining[0], float("-inf")
        for i in remaining:
            penalty = max((sim(i, j) for j in selected), default=0.0)
            score = lambda_mult * pool[i]["score"] - (1 - lambda_mult) * penalty
            if score > best_score:
                best, best_score = i, score
        selected.append(best)
        remaining.remove(best)
    return selected


def _rank(query: str, query_vec: list[float], rows: list[tuple], model_name: str, k: int) -> list[dict]:
    settings = get_knowledge_settings()
    texts = [r[1] for r in rows]
    # Vectors from a different embedding model live in a different space.
    embeddings = [r[5] if r[6] == model_name else None for r in rows]

    vector_order = _vector_order(query_vec, embeddings)
    keyword_order = _bm25_order(query, texts)
    rankings = [o for o in (vector_order, keyword_order) if o]
    if not rankings:
        return []
    vector_ranked, keyword_ranked = set(vector_order), set(keyword_order)

    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, start=1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (settings.RAG_RRF_K + rank)
    order = sorted(fused, key=fused.get, reverse=True)
    top = fused[order[0]]

    pool_idx = order[: max(k, settings.RAG_RERANK_CANDIDATES)]
    ce = _rerank_scores(query, [texts[i] for i in pool_idx]) if settings.RAG_RERANK_ENABLED else None
    w = settings.RAG_CROSS_ENCODER_WEIGHT
    pool: list[dict] = []
    for pos, i in enumerate(pool_idx):
        hybrid = fused[i] / top if top else 0.0
        score = w * ce[pos] + (1 - w) * hybrid if ce is not None else hybrid
        chunk_id, content, filename, document_id, chunk_index, _, _, metadata = rows[i]
        pool.append(
            {
                "id": chunk_id,
                "content": content,
                "filename": filename,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "metadata": metadata or {},
                "score": round(score, 4),
                "retrieval_method": (
                    "hybrid" if i in vector_ranked and i in keyword_ranked
                    else "semantic" if i in vector_ranked else "keyword"
                ),
            }
        )
    pool.sort(key=lambda c: c["score"], reverse=True)
    by_id = {r[0]: r[5] if r[6] == model_name else None for r in rows}
    vectors = [np.asarray(by_id[c["id"]], dtype=np.float32) if by_id[c["id"]] else None for c in pool]
    return [pool[i] for i in _mmr_select(pool, vectors, k)]


async def retrieve(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    tenant_id: str,
    query: str,
    k: int | None = None,
) -> list[dict]:
    """Top-k chunks of one knowledge base for ``query``, each with the document
    it came from so an answer can cite it. Scoped to ``tenant_id``."""
    k = k or get_knowledge_settings().RAG_TOP_K
    query = (query or "").strip()
    if not query:
        return []
    rows = (
        await db.execute(
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.content,
                KnowledgeDocument.filename,
                KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index,
                KnowledgeChunk.embedding,
                KnowledgeChunk.embedding_model,
                KnowledgeChunk.source_metadata,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeDocument.status == "ready",
            )
        )
    ).all()
    if not rows:
        return []
    embedder = get_embedder()
    query_vec = await embedder.embed_query(query)
    return await asyncio.to_thread(_rank, query, query_vec, [tuple(r) for r in rows], embedder.model_name, k)


__all__ = ["retrieve"]
