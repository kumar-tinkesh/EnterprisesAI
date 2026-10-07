"""Knowledge-base (RAG) settings, read from the environment / ``.env``."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # "fastembed": local ONNX model, no API key, works offline (default).
    # "gateway": the LLM gateway's configured embedding provider.
    KNOWLEDGE_EMBEDDING_BACKEND: str = "fastembed"
    KNOWLEDGE_EMBEDDING_MODEL_FASTEMBED: str = "BAAI/bge-small-en-v1.5"
    # Empty = the gateway provider's own default embedding model.
    KNOWLEDGE_EMBEDDING_MODEL_GATEWAY: str = ""

    RAG_SEMANTIC_UNIT_TOKENS: int = 128
    RAG_FINAL_CHUNK_TOKENS: int = 384
    RAG_SEMANTIC_MIN_SIMILARITY: float = 0.55
    RAG_TOP_K: int = 8
    RAG_RERANK_CANDIDATES: int = 24
    RAG_RRF_K: int = 60
    RAG_CROSS_ENCODER_WEIGHT: float = 0.70
    RAG_RERANK_ENABLED: bool = True

    RAG_MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    RAG_MAX_OFFICE_ARCHIVE_MEMBERS: int = 10_000
    RAG_MAX_OFFICE_UNCOMPRESSED_BYTES: int = 150 * 1024 * 1024
    RAG_MAX_OFFICE_COMPRESSION_RATIO: int = 100

    # Hard ceiling on one document's processing time, so a document can never
    # sit in "processing" forever.
    RAG_DOCUMENT_TIMEOUT_SECONDS: int = 300


@lru_cache
def get_knowledge_settings() -> KnowledgeSettings:
    return KnowledgeSettings()
