"""Knowledge-base REST endpoints (mounted at ``/api/v1/knowledge-bases``).

Every knowledge base belongs to a tenant and is visible to all of that
tenant's members (tenant admins, tenant users, and a solo user's personal
tenant). Vendor admins have no tenant and get 403. Anyone in the tenant can
add documents; renaming/deleting a knowledge base is for its creator or a
tenant admin, and a document can also be edited/deleted by whoever added it.

Routes:
    POST   ""                                  create
    GET    ""                                  list (this tenant)
    GET    /{kb_id}                            one
    PATCH  /{kb_id}                            rename / describe
    DELETE /{kb_id}                            delete with all documents
    GET    /{kb_id}/documents                  list documents
    POST   /{kb_id}/documents                  upload a file (multipart)
    POST   /{kb_id}/text                       add typed/pasted text
    GET    /{kb_id}/documents/{doc_id}/text    an editable document's text
    PUT    /{kb_id}/documents/{doc_id}/text    replace that text and re-index
    DELETE /{kb_id}/documents/{doc_id}         delete one document
    POST   /{kb_id}/search                     hybrid retrieval (top-k chunks)

SQLite doesn't enforce ``ON DELETE CASCADE`` by default, so deletes remove
child rows explicitly.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.core.roles import Roles
from src.db.session import get_db

from knowledge.api.v1.schemas import (
    DocumentOut,
    DocumentTextOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    KnowledgeTextCreate,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from knowledge.services import ingest
from knowledge.services.document_safety import DocumentUploadError, upload_limits, validate_uploaded_document
from knowledge.services.retrieval import retrieve

router = APIRouter()

# Uploads whose text is kept so they can be edited later (binary formats are delete-and-re-add).
EDITABLE_UPLOAD_EXTENSIONS = (".md", ".markdown", ".txt")


async def get_tenant_member(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Knowledge bases belong to a tenant; this account has none.",
        )
    return user


def _can_manage(kb: KnowledgeBase, user: CurrentUser) -> bool:
    return kb.owner_id == user.id or user.role == Roles.TENANT_ADMIN


def _can_edit_document(kb: KnowledgeBase, doc: KnowledgeDocument, user: CurrentUser) -> bool:
    return doc.owner_id == user.id or _can_manage(kb, user)


def _text_markdown(title: str, content: str) -> str:
    """How typed knowledge is stored and indexed: a Markdown heading, then the text."""
    return f"# {title}\n\n{content.strip()}\n"


def _text_filename(title: str, ext: str = ".md") -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") or "knowledge")[:80] + ext


def _split_title(filename: str, text: str) -> tuple[str, str]:
    """Stored text -> (title, body): the leading "# heading" if there is one, else the file name."""
    first, _, rest = (text or "").partition("\n")
    if first.startswith("# "):
        return first[2:].strip(), rest.strip()
    stem = filename.rsplit(".", 1)[0].replace("_", " ").strip()
    return stem or "Knowledge", (text or "").strip()


def _validate(filename: str, data: bytes) -> None:
    try:
        validate_uploaded_document(filename, data, limits=upload_limits())
    except DocumentUploadError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc


async def _kb_out(db: AsyncSession, kb: KnowledgeBase, user: CurrentUser) -> KnowledgeBaseOut:
    count = (
        await db.execute(
            select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.knowledge_base_id == kb.id)
        )
    ).scalar_one()
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description or "",
        owner_id=kb.owner_id,
        document_count=count,
        can_manage=_can_manage(kb, user),
        created_at=kb.created_at,
    )


def _doc_out(doc: KnowledgeDocument) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        error_message=doc.error_message,
        chunk_count=doc.chunk_count or 0,
        editable=doc.content_text is not None,
        created_at=doc.created_at,
    )


async def _get_kb(db: AsyncSession, kb_id: str, user: CurrentUser) -> KnowledgeBase:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id)
        )
    ).scalars().first()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


async def _get_doc(db: AsyncSession, kb: KnowledgeBase, doc_id: str) -> KnowledgeDocument:
    doc = (
        await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == doc_id, KnowledgeDocument.knowledge_base_id == kb.id
            )
        )
    ).scalars().first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _forbid(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


# ── Knowledge bases ──────────────────────────────────────────────────────────


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = KnowledgeBase(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        name=" ".join(payload.name.split()),
        description=payload.description.strip(),
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kbs = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.tenant_id == user.tenant_id)
            .order_by(KnowledgeBase.created_at.desc())
        )
    ).scalars().all()
    return [await _kb_out(db, kb, user) for kb in kbs]


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: str,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    return await _kb_out(db, await _get_kb(db, kb_id, user), user)


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    if not _can_manage(kb, user):
        raise _forbid("Only its creator or a tenant admin can change this knowledge base.")
    if payload.name is not None:
        kb.name = " ".join(payload.name.split())
    if payload.description is not None:
        kb.description = payload.description.strip()
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    if not _can_manage(kb, user):
        raise _forbid("Only its creator or a tenant admin can delete this knowledge base.")
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == kb.id))
    await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == kb.id))
    await db.delete(kb)
    await db.commit()


# ── Documents ────────────────────────────────────────────────────────────────


@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: str,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    docs = (
        await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == kb.id)
            .order_by(KnowledgeDocument.created_at.asc())
        )
    ).scalars().all()
    return [_doc_out(d) for d in docs]


@router.post("/{kb_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    # Read one byte past the limit so an oversized upload is rejected without
    # copying the whole thing into memory.
    data = await file.read(upload_limits().max_upload_bytes + 1)
    filename = file.filename or "upload"
    _validate(filename, data)

    content_text = None
    if filename.lower().endswith(EDITABLE_UPLOAD_EXTENSIONS):
        try:
            content_text = data.decode("utf-8")
        except UnicodeDecodeError:
            content_text = None  # still indexed, just not editable in the UI
    doc = KnowledgeDocument(
        knowledge_base_id=kb.id,
        tenant_id=kb.tenant_id,
        owner_id=user.id,
        filename=filename,
        status="processing",
        content_text=content_text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    background.add_task(ingest.process_document, doc.id, filename, data)
    return _doc_out(doc)


@router.post("/{kb_id}/text", response_model=DocumentOut, status_code=201)
async def add_text_document(
    kb_id: str,
    payload: KnowledgeTextCreate,
    background: BackgroundTasks,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    """Knowledge typed or pasted in the UI, stored and indexed exactly like an
    uploaded Markdown file."""
    kb = await _get_kb(db, kb_id, user)
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Knowledge text is empty.")
    title = " ".join(payload.title.split())
    filename = _text_filename(title)
    text = _text_markdown(title, payload.content)
    data = text.encode("utf-8")
    _validate(filename, data)
    doc = KnowledgeDocument(
        knowledge_base_id=kb.id,
        tenant_id=kb.tenant_id,
        owner_id=user.id,
        filename=filename,
        status="processing",
        content_text=text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    background.add_task(ingest.process_document, doc.id, filename, data)
    return _doc_out(doc)


@router.get("/{kb_id}/documents/{doc_id}/text", response_model=DocumentTextOut)
async def get_document_text(
    kb_id: str,
    doc_id: str,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_doc(db, await _get_kb(db, kb_id, user), doc_id)
    if doc.content_text is None:
        raise HTTPException(
            status_code=409,
            detail="This document's text isn't kept (PDF, Word…). Delete it and add it again to change it.",
        )
    title, content = _split_title(doc.filename, doc.content_text)
    return DocumentTextOut(id=doc.id, filename=doc.filename, title=title, content=content)


@router.put("/{kb_id}/documents/{doc_id}/text", response_model=DocumentOut)
async def update_document_text(
    kb_id: str,
    doc_id: str,
    payload: KnowledgeTextCreate,
    background: BackgroundTasks,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    """Replace an editable document's text and index it again (same document id)."""
    kb = await _get_kb(db, kb_id, user)
    doc = await _get_doc(db, kb, doc_id)
    if not _can_edit_document(kb, doc, user):
        raise _forbid("Only whoever added this document, the knowledge base's creator, or a tenant admin can edit it.")
    if doc.content_text is None:
        raise HTTPException(status_code=409, detail="This document can't be edited. Delete it and add it again.")
    if doc.status == "processing":
        raise HTTPException(status_code=409, detail="This document is still being indexed. Try again in a moment.")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Knowledge text is empty.")
    title = " ".join(payload.title.split())
    ext = "." + doc.filename.rsplit(".", 1)[-1].lower() if "." in doc.filename else ".md"
    filename = _text_filename(title, ext if ext in EDITABLE_UPLOAD_EXTENSIONS else ".md")
    text = _text_markdown(title, payload.content)
    data = text.encode("utf-8")
    _validate(filename, data)
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    doc.filename, doc.content_text, doc.status, doc.error_message, doc.chunk_count = (
        filename, text, "processing", None, 0,
    )
    await db.commit()
    await db.refresh(doc)
    background.add_task(ingest.process_document, doc.id, filename, data)
    return _doc_out(doc)


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    doc = await _get_doc(db, kb, doc_id)
    if not _can_edit_document(kb, doc, user):
        raise _forbid("Only whoever added this document, the knowledge base's creator, or a tenant admin can delete it.")
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    await db.delete(doc)
    await db.commit()


# ── Retrieval ────────────────────────────────────────────────────────────────


@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search_knowledge_base(
    kb_id: str,
    payload: SearchRequest,
    user: CurrentUser = Depends(get_tenant_member),
    db: AsyncSession = Depends(get_db),
):
    kb = await _get_kb(db, kb_id, user)
    try:
        hits = await retrieve(
            db, knowledge_base_id=kb.id, tenant_id=kb.tenant_id, query=payload.query, k=payload.top_k
        )
    except Exception as exc:  # embedding backend unavailable, etc.
        raise HTTPException(status_code=503, detail=f"Search is unavailable right now: {exc}") from exc
    return SearchResponse(query=payload.query, results=[SearchHit(**h) for h in hits])
