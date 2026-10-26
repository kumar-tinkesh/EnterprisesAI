"""Request/response schemas for the knowledge-base API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    document_count: int
    can_manage: bool
    created_at: datetime


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str  # processing | ready | error
    error_message: str | None = None
    chunk_count: int = 0
    # True when its text is kept (typed, or uploaded as .md/.txt), so it can be opened and edited.
    editable: bool = False
    created_at: datetime


class KnowledgeTextCreate(BaseModel):
    """Knowledge typed or pasted instead of uploaded; stored as a Markdown document."""

    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=200_000)


class DocumentTextOut(BaseModel):
    """An editable document's text, split back into the title and body it was saved from."""

    id: str
    filename: str
    title: str
    content: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    id: str
    content: str
    filename: str
    document_id: str
    chunk_index: int
    score: float
    retrieval_method: str
    metadata: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
