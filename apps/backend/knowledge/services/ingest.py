"""Document ingestion: parse -> semantic chunks -> embeddings -> stored chunks.

Runs as a FastAPI background task so an upload returns immediately with
status ``processing`` and later flips to ``ready`` or ``error`` (the UI polls).
Parsing (pdfplumber / python-docx / openpyxl / OCR) is CPU-bound and runs in a
worker thread; the whole document is bounded by
``RAG_DOCUMENT_TIMEOUT_SECONDS`` so it can never sit in ``processing`` forever.

Background tasks open their own DB sessions from ``session_factory`` (the
request's session is closed by then); tests point it at their own engine.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, select, update

from knowledge.config import get_knowledge_settings
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services.chunking import chunk_document
from knowledge.services.document_parser import enrich_pdf_image_ocr, parse_document
from knowledge.services.embeddings import get_embedder

logger = logging.getLogger("knowledge.ingest")


def session_factory():
    from src.db.session import SessionLocal

    return SessionLocal()


async def _set_status(document_id: str, status: str, error: str | None) -> None:
    async with session_factory() as db:
        await db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .values(status=status, error_message=error)
        )
        await db.commit()


async def _index(document_id: str, filename: str, data: bytes) -> None:
    def parse():
        return enrich_pdf_image_ocr(parse_document(filename, data), data)

    parsed = await asyncio.to_thread(parse)
    embedder = get_embedder()
    chunks = await chunk_document(parsed, embedder)
    vectors = await embedder.embed_texts([chunk.content for chunk in chunks]) if chunks else []

    async with session_factory() as db:
        document = await db.get(KnowledgeDocument, document_id)
        if document is None:  # deleted while it was being processed
            return
        # Re-indexing an edited document: never mix old and new chunks.
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    knowledge_base_id=document.knowledge_base_id,
                    tenant_id=document.tenant_id,
                    chunk_index=index,
                    content=chunk.content,
                    source_metadata=chunk.metadata,
                    embedding=vector,
                    embedding_model=embedder.model_name,
                )
            )
        document.status = "ready"
        document.chunk_count = len(chunks)
        document.error_message = None if chunks else "No readable text found; no searchable content was stored."
        await db.commit()


async def process_document(document_id: str, filename: str, data: bytes) -> None:
    """Background entry point: index one document, recording any failure on it."""
    timeout = get_knowledge_settings().RAG_DOCUMENT_TIMEOUT_SECONDS
    try:
        await asyncio.wait_for(_index(document_id, filename, data), timeout=timeout)
    except TimeoutError:
        await _set_status(
            document_id,
            "error",
            f"Processing timed out after {timeout}s. The file may be too large or complex, "
            "or an embedding call hung. Try again.",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to the user as the document's error
        logger.warning("knowledge_ingest_failed document=%s", document_id, exc_info=True)
        await _set_status(document_id, "error", str(exc) or exc.__class__.__name__)


async def fail_interrupted_documents() -> int:
    """Mark documents left in ``processing`` by a previous process as failed.

    Background tasks die with the process; without this a restart mid-upload
    would leave the document spinning in the UI forever.
    """
    async with session_factory() as db:
        ids = (
            await db.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.status == "processing"))
        ).scalars().all()
        if ids:
            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id.in_(ids))
                .values(status="error", error_message="Processing was interrupted by a server restart. Upload it again.")
            )
            await db.commit()
        return len(ids)


__all__ = ["process_document", "fail_interrupted_documents"]
