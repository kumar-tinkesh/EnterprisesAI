"""Knowledge domain: tenant-scoped knowledge bases for retrieval (RAG).

A knowledge base is a named collection of documents (uploaded files or text
typed in the UI). Each document is parsed, split into semantic chunks, and
every chunk is embedded; retrieval ranks a knowledge base's chunks against a
query (vector + BM25, fused, reranked, diversified).

Ported from the AI Marketplace's ``app/rag`` + ``api/v1/knowledge_bases``,
adapted to this codebase: async SQLAlchemy, tenant scoping instead of
organisations, and embeddings stored as portable JSON (no pgvector) so the
same schema runs on SQLite and PostgreSQL — matching how ``vendor.models``
stores tool/server embeddings.
"""
