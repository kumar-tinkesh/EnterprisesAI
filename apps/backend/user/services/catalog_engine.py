"""Catalog engine — the AI Compiler's authorised capability view.

Phase 1 implements **access-filtering only**: given an authenticated user,
return the MCP servers they are allowed to bind to an agent.

    * ``vendor_admin`` → every registered MCP server.
    * ``solo_user``     → MCP servers flagged ``is_global``.
    * ``tenant_user`` / ``tenant_admin`` → ``is_global`` MCP servers **plus**
      MCP servers granted to the caller's tenant via ``tenant_resource_grants``.

Read-only: this module only ever queries ``vendor.models`` — it never
mutates a server/tool row. Registration, verification, and embedding are
``vendor.services.mcp_service`` / ``vendor.services.embedding``, both
off-limits to this ``user`` package (see the repo's import-linter
contracts; ``vendor.models``, ``vendor.services.text_repr`` and
``vendor.services.embedding.embed_text`` are the only narrow exceptions,
each pure/read-only).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.roles import Roles

from vendor.models import MCPTool, TenantResourceGrant, VendorMCPServer
from vendor.services.embedding import embed_text
from vendor.services.text_repr import server_text, tool_text

from user.services import hybrid_search


async def get_authorized_vendor_catalog(
    db: AsyncSession, *, user: CurrentUser
) -> list[VendorMCPServer]:
    """Return the MCP servers the calling user is authorised to use."""
    if user.role == Roles.VENDOR_ADMIN:
        result = await db.execute(select(VendorMCPServer).order_by(VendorMCPServer.name))
        return list(result.scalars().all())

    if user.role == Roles.SOLO_USER:
        result = await db.execute(
            select(VendorMCPServer)
            .where(VendorMCPServer.is_global.is_(True))
            .order_by(VendorMCPServer.name)
        )
        return list(result.scalars().all())

    grant_subq = select(TenantResourceGrant.resource_id).where(
        TenantResourceGrant.tenant_id == user.tenant_id,
        TenantResourceGrant.resource_type == "mcp",
    )
    result = await db.execute(
        select(VendorMCPServer)
        .where(
            or_(
                VendorMCPServer.is_global.is_(True),
                VendorMCPServer.id.in_(grant_subq),
            )
        )
        .order_by(VendorMCPServer.name)
    )
    return list(result.scalars().all())


def _rank_servers(servers: list[VendorMCPServer], *, query: str, q_vec, top_k: int):
    return hybrid_search.rank(
        servers,
        query=query,
        query_vector=q_vec,
        top_k=top_k,
        text_of=server_text,
        embedding_of=lambda s: s.embedding,
        dim_of=lambda s: s.dim,
    )


def _rank_tools(tools: list[MCPTool], *, query: str, q_vec, top_k: int):
    return hybrid_search.rank(
        tools,
        query=query,
        query_vector=q_vec,
        top_k=top_k,
        text_of=tool_text,
        embedding_of=lambda t: t.embedding,
        dim_of=lambda t: t.dim,
    )


async def get_authorized_vendor_catalog_semantic(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    top_k: int = 5,
    embedding_provider: Optional[str] = None,
) -> list[VendorMCPServer]:
    """Hybrid-search match: rank the access-filtered catalog against
    ``query``.

    Access control is enforced **first**, then the candidate servers are
    ranked by :func:`hybrid_search.rank` (vector + BM25 + rerank — see that
    module for why). BM25 and the reranker work even when the query
    couldn't be embedded (provider down, etc.), so only a genuinely empty
    query or zero candidates skips ranking entirely.
    """
    candidates = await get_authorized_vendor_catalog(db, user=user)
    if not candidates or not query:
        return candidates[:top_k]

    q_embedded = await embed_text(query, provider=embedding_provider)
    q_vec = q_embedded[0] if q_embedded else None

    ranked = _rank_servers(candidates, query=query, q_vec=q_vec, top_k=top_k)
    return ranked or candidates[:top_k]


async def get_relevant_tools_semantic(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    top_k_servers: int = 5,
    top_k_tools: int = 8,
    embedding_provider: Optional[str] = None,
) -> list[tuple[VendorMCPServer, MCPTool, Optional[float]]]:
    """Two-stage hybrid tool retrieval — the actual "which tool(s) can
    answer this query" lookup, for handing to an LLM as function-calling
    candidates. Does **not** call any tool; it only selects and returns them
    with their ``input_schema`` (parameters).

    Stage 1: rank the caller's *access-filtered* catalog (same rules as
    :func:`get_authorized_vendor_catalog`) down to ``top_k_servers``.
    Stage 2: within only those servers' tools, rank down to ``top_k_tools``.
    Both stages go through :func:`hybrid_search.rank` (vector + BM25 +
    cross-encoder rerank).

    The query is embedded once and reused for both stages. Returns
    ``(server, tool, score)`` triples, best match first; ``score`` is the
    tool's cosine similarity to the query when an embedding was available,
    else ``None`` (BM25/rerank still ranked it, there's just no vector
    score to report).
    """
    candidates = await get_authorized_vendor_catalog(db, user=user)
    if not candidates or not query:
        return []

    q_embedded = await embed_text(query, provider=embedding_provider)
    q_vec = q_embedded[0] if q_embedded else None

    servers = _rank_servers(candidates, query=query, q_vec=q_vec, top_k=top_k_servers)
    if not servers:
        servers = candidates[:top_k_servers]
    if not servers:
        return []

    server_ids = [s.id for s in servers]
    server_map = {s.id: s for s in servers}
    tools = (
        await db.execute(select(MCPTool).where(MCPTool.mcp_server_id.in_(server_ids)))
    ).scalars().all()
    if not tools:
        return []

    ranked_tools = _rank_tools(list(tools), query=query, q_vec=q_vec, top_k=top_k_tools)
    if not ranked_tools:
        ranked_tools = list(tools)[:top_k_tools]

    return [
        (
            server_map[t.mcp_server_id],
            t,
            hybrid_search.cosine_similarity(q_vec, t.embedding) if q_vec and t.embedding else None,
        )
        for t in ranked_tools
    ]


# Re-exported for backward compatibility — this used to be defined here.
cosine_similarity = hybrid_search.cosine_similarity


__all__ = [
    "get_authorized_vendor_catalog",
    "get_authorized_vendor_catalog_semantic",
    "get_relevant_tools_semantic",
    "cosine_similarity",
]
