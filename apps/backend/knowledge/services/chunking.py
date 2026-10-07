"""Token-aware semantic chunking for parsed documents.

1. Every parsed element is split into small *semantic units* (paragraphs /
   sentences / table rows) under ``RAG_SEMANTIC_UNIT_TOKENS``.
2. All units are embedded.
3. Neighbouring units are merged into a chunk while they stay in the same
   container (page / sheet / table / heading), stay semantically similar
   (cosine above a threshold derived from the document's own similarity
   distribution), and fit under ``RAG_FINAL_CHUNK_TOKENS``.

Each chunk is prefixed with its context (page, sheet, heading path, table
headers) so it reads correctly on its own when retrieved.
"""
from __future__ import annotations

import asyncio
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Protocol

from knowledge.config import get_knowledge_settings
from knowledge.services.document_parser import DocumentElement, ParsedDocument
from knowledge.services.embeddings import get_embedder


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class _EmbeddingService(Protocol):
    model_name: str
    max_input_tokens: int

    def count_tokens(self, text: str) -> int: ...
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ChunkDraft:
    content: str
    metadata: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True)
class _SemanticUnit:
    payload: str
    semantic_text: str
    metadata: dict[str, str | int]

    def container_key(self) -> tuple[object, ...]:
        return tuple(self.metadata.get(key) for key in ("page", "sheet", "table", "heading_path", "headers"))


def _split_to_unit_limit(text: str, embedder: _EmbeddingService, limit: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if embedder.count_tokens(text) <= limit:
        return [text]
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(text) if sentence.strip()]
    if len(sentences) > 1:
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and embedder.count_tokens(candidate) > limit:
                pieces.extend(_split_to_unit_limit(current, embedder, limit))
                current = sentence
            else:
                current = candidate
        if current:
            pieces.extend(_split_to_unit_limit(current, embedder, limit))
        return pieces

    # Last-resort split for one oversized sentence.
    words = text.split()
    pieces, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if current and embedder.count_tokens(candidate) > limit:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _table_units(element: DocumentElement, embedder: _EmbeddingService, unit_limit: int) -> list[_SemanticUnit]:
    lines = [line.strip() for line in element.text.splitlines() if line.strip()]
    if not lines:
        return []
    header = element.metadata.get("headers", "")
    separator = len(lines) > 1 and lines[1].replace("|", "").replace("-", "").strip() == ""
    data_lines = lines[2:] if separator else lines[1:]
    if not data_lines:
        data_lines = lines
    units: list[_SemanticUnit] = []
    base_row = element.metadata.get("row_start")
    for offset, row in enumerate(data_lines):
        metadata = dict(element.metadata)
        if isinstance(base_row, int):
            metadata["row_start"] = base_row + offset + 1
            metadata["row_end"] = base_row + offset + 1
        else:
            metadata["table_row_start"] = offset + 1
            metadata["table_row_end"] = offset + 1
        for payload in _split_to_unit_limit(row, embedder, unit_limit):
            semantic_text = f"Headers: {header}\n{payload}" if header else payload
            units.append(_SemanticUnit(payload, semantic_text, metadata))
    return units


def _element_units(element: DocumentElement, embedder: _EmbeddingService, unit_limit: int) -> list[_SemanticUnit]:
    if element.kind == "heading":
        return []
    if element.kind == "table":
        return _table_units(element, embedder, unit_limit)
    units: list[_SemanticUnit] = []
    for paragraph in (part.strip() for part in re.split(r"\n\s*\n", element.text)):
        if not paragraph:
            continue
        for payload in _split_to_unit_limit(paragraph, embedder, unit_limit):
            units.append(_SemanticUnit(payload, payload, dict(element.metadata)))
    return units


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def _threshold(similarities: list[float], floor: float) -> float:
    if not similarities:
        return floor
    mean = statistics.fmean(similarities)
    spread = statistics.pstdev(similarities) if len(similarities) > 1 else 0.0
    return max(floor, min(0.95, mean - spread))


def _render_chunk(units: list[_SemanticUnit], document_type: str, model_name: str) -> ChunkDraft:
    first = units[0]
    metadata: dict[str, str | int] = {"document_type": document_type, "embedding_model": model_name}
    metadata.update(first.metadata)
    if "row_start" in first.metadata:
        metadata["row_start"] = first.metadata["row_start"]
        metadata["row_end"] = units[-1].metadata.get("row_end", first.metadata["row_start"])
    if "table_row_start" in first.metadata:
        metadata["table_row_start"] = first.metadata["table_row_start"]
        metadata["table_row_end"] = units[-1].metadata.get("table_row_end", first.metadata["table_row_start"])
    context = []
    for label, key in (("Page", "page"), ("Sheet", "sheet"), ("Heading", "heading_path"), ("Headers", "headers")):
        if (value := metadata.get(key)) is not None:
            context.append(f"{label}: {value}")
    if (row_start := metadata.get("row_start")) is not None:
        context.append(f"Rows: {row_start}-{metadata.get('row_end', row_start)}")
    return ChunkDraft("\n".join(context + [unit.payload for unit in units]).strip(), metadata)


def _build_units(document: ParsedDocument, embedder: _EmbeddingService, unit_limit: int) -> list[_SemanticUnit]:
    return [unit for element in document.elements for unit in _element_units(element, embedder, unit_limit)]


def _assemble(
    document: ParsedDocument,
    units: list[_SemanticUnit],
    vectors: list[list[float]],
    embedder: _EmbeddingService,
    final_target: int,
    min_similarity: float,
) -> list[ChunkDraft]:
    similarities = [
        _cosine(vectors[index - 1], vectors[index])
        for index in range(1, len(units))
        if units[index - 1].container_key() == units[index].container_key()
    ]
    threshold = _threshold(similarities, min_similarity)
    drafts: list[ChunkDraft] = []
    current: list[_SemanticUnit] = []
    seen: set[str] = set()

    def emit() -> None:
        nonlocal current
        if not current:
            return
        draft = _render_chunk(current, document.document_type, embedder.model_name)
        if embedder.count_tokens(draft.content) > embedder.max_input_tokens:
            raise ValueError("A rendered semantic chunk exceeds the embedding model token limit.")
        if draft.content and draft.content not in seen:
            seen.add(draft.content)
            drafts.append(draft)
        current = []

    for index, unit in enumerate(units):
        if current:
            previous = units[index - 1]
            similarity = _cosine(vectors[index - 1], vectors[index])
            candidate = _render_chunk(current + [unit], document.document_type, embedder.model_name)
            if (
                previous.container_key() != unit.container_key()
                or similarity < threshold
                or embedder.count_tokens(candidate.content) > final_target
            ):
                emit()
        current.append(unit)
    emit()
    return drafts


async def chunk_document(document: ParsedDocument, embedder: _EmbeddingService | None = None) -> list[ChunkDraft]:
    """Create the final semantic chunks for ``document`` (only these are stored)."""
    settings = get_knowledge_settings()
    active_embedder = embedder or get_embedder()
    if settings.RAG_FINAL_CHUNK_TOKENS >= active_embedder.max_input_tokens:
        raise ValueError("Final chunk target must be below the active embedding model token limit.")

    units = await asyncio.to_thread(_build_units, document, active_embedder, settings.RAG_SEMANTIC_UNIT_TOKENS)
    if not units:
        return []
    vectors = await active_embedder.embed_texts([unit.semantic_text for unit in units])
    return await asyncio.to_thread(
        _assemble,
        document,
        units,
        vectors,
        active_embedder,
        settings.RAG_FINAL_CHUNK_TOKENS,
        settings.RAG_SEMANTIC_MIN_SIMILARITY,
    )


__all__ = ["ChunkDraft", "chunk_document"]
