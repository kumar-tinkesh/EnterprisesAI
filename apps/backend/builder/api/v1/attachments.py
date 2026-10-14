"""Files sent with a chat message (mounted under ``/api/v1/builder``).

    POST   /attachments                  upload one (multipart "file") -> {id, filename, kind, size, chars}
    DELETE /attachments/{attachment_id}

Then start an agent run with ``attachment_ids``. A document (PDF, DOCX, XLSX,
CSV, Markdown, text) is checked and read once, here, with the knowledge
base's own safety checks and parsers; the agent gets its text with the
message. An image (JPG, PNG) is kept as is and sent to the model with the
message, so the agent needs a model that can see images. Private to whoever
uploaded it.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.models import BuilderAttachment

router = APIRouter()

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# What's kept of a document's text (the agent sees less: runtime.MAX_ATTACHMENT_TEXT).
MAX_TEXT_CHARS = 200_000
MAX_PER_MESSAGE = 5


class AttachmentOut(BaseModel):
    id: str
    filename: str
    kind: str  # document | image
    size: int
    # Characters of text read from a document (0 for an image).
    chars: int


def _read(filename: str, data: bytes) -> tuple[str, str, str]:
    """-> (kind, content type, text). Raises DocumentUploadError."""
    from knowledge.services.document_parser import parse_document
    from knowledge.services.document_safety import DocumentUploadError, validate_uploaded_document

    detected = validate_uploaded_document(filename, data)
    if detected.kind == "image":
        if len(data) > MAX_IMAGE_BYTES:
            raise DocumentUploadError(f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
        return "image", detected.mime_type, ""
    parsed = parse_document(filename, data, detected)
    text = "\n\n".join(e.text for e in parsed.elements if e.text.strip())
    return "document", detected.mime_type, text[:MAX_TEXT_CHARS]


def _out(a: BuilderAttachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, filename=a.filename, kind=a.kind, size=a.size, chars=len(a.text or ""))


@router.post("/attachments", response_model=AttachmentOut, status_code=201)
async def upload(file: UploadFile = File(...), user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    from knowledge.services.document_safety import DocumentUploadError

    filename = (file.filename or "").strip()[:255]
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail=f"Files can be at most {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.")
    try:
        kind, content_type, text = await asyncio.to_thread(_read, filename, data)
    except DocumentUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — a parser failing on one odd file is the file's problem
        raise HTTPException(status_code=422, detail=f"Couldn't read {filename}: {exc}") from exc
    attachment = BuilderAttachment(
        tenant_id=user.tenant_id, owner_id=user.id, filename=filename, kind=kind, content_type=content_type,
        size=len(data), text=text if kind == "document" else None, data=data if kind == "image" else None,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return _out(attachment)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def remove(attachment_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    attachment = (
        await db.execute(select(BuilderAttachment).where(BuilderAttachment.id == attachment_id, BuilderAttachment.owner_id == user.id))
    ).scalars().first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await db.delete(attachment)
    await db.commit()


async def attachments_for_run(db: AsyncSession, user: CurrentUser, ids: list[str]) -> list[dict]:
    """[{id, filename, kind}] for a run's input — the caller's own, in the order given."""
    ids = list(dict.fromkeys(ids))
    if len(ids) > MAX_PER_MESSAGE:
        raise HTTPException(status_code=422, detail=f"Attach at most {MAX_PER_MESSAGE} files to one message.")
    if not ids:
        return []
    rows = {
        a.id: a
        for a in (
            await db.execute(select(BuilderAttachment).where(BuilderAttachment.id.in_(ids), BuilderAttachment.owner_id == user.id))
        ).scalars()
    }
    missing = [i for i in ids if i not in rows]
    if missing:
        raise HTTPException(status_code=404, detail="An attached file was not found; upload it again.")
    return [{"id": a.id, "filename": a.filename, "kind": a.kind} for a in (rows[i] for i in ids)]
