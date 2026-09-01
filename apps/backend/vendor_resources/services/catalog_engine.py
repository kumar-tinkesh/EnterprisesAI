"""Catalog engine — the AI Compiler's authorised capability view.

Phase 1 implements **access-filtering only**: given an authenticated user,
return the MCP servers they are allowed to bind to an agent.

    * ``vendor_admin`` → every registered MCP server.
    * ``solo_user``     → MCP servers flagged ``is_global``.
    * ``tenant_user`` / ``tenant_admin`` → ``is_global`` MCP servers **plus**
      MCP servers granted to the caller's tenant via ``tenant_resource_grants``.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.roles import Roles

from vendor_resources.models import TenantResourceGrant, VendorMCPServer


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


async def get_authorized_vendor_catalog_semantic(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    top_k: int = 5,
    embedding_provider: Optional[str] = None,
) -> list[VendorMCPServer]:
    """Semantic match: rank the access-filtered catalog against ``query``.

    Access control is enforced **first**, then the candidate servers are
    ranked by cosine similarity between the query embedding and each
    server's stored embedding. If no embeddings are available or the
    query can't be embedded, falls back to the access-filtered list
    truncated to ``top_k``.
    """
    candidates = await get_authorized_vendor_catalog(db, user=user)
    if not candidates or not query:
        return candidates[:top_k]

    q_embedded = await embed_text(query, provider=embedding_provider)
    if q_embedded is None:
        return candidates[:top_k]
    q_vec, _ = q_embedded

    candidate_ids = [t.id for t in candidates]
    emap = {
        e.id: e
        for e in (
            await db.execute(
                select(VendorMCPServer).where(VendorMCPServer.id.in_(candidate_ids))
            )
        ).scalars().all()
    }

    scored: list[tuple[float, VendorMCPServer]] = []
    for server in candidates:
        emb = emap.get(server.id)
        if emb is None or emb.dim != len(q_vec):
            continue
        scored.append((cosine_similarity(q_vec, emb.embedding), server))

    if not scored:
        return candidates[:top_k]

    scored.sort(key=lambda s: s[0], reverse=True)
    return [server for _, server in scored[:top_k]]


async def embed_text(
    text: str, *, provider: Optional[str] = None, model: Optional[str] = None
) -> Optional[tuple[list[float], str]]:
    """Embed ``text`` via the gateway. Returns ``(vector, model)`` or ``None``."""
    if not text:
        return None
    try:
        from apps.llm_gateway.gateway import LLMGateway
        from apps.llm_gateway.exceptions import LLMGatewayError
        from apps.llm_gateway.types import EmbeddingResponse
        from functools import lru_cache

        @lru_cache
        def _get_gw() -> LLMGateway:
            return LLMGateway.from_env()

        gw = _get_gw()
        resp: EmbeddingResponse = await gw.embed([text], provider=provider, model=model)
    except LLMGatewayError:
        return None
    except Exception:
        return None

    if not resp.embeddings:
        return None
    return list(resp.embeddings[0]), resp.model or (model or "")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a)) ** 0.5
    nb = (sum(y * y for y in b)) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


__all__ = [
    "get_authorized_vendor_catalog",
    "get_authorized_vendor_catalog_semantic",
]