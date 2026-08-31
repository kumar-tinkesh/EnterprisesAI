"""Catalog engine — the AI Compiler's authorised capability view.

Phase 1 implements **access-filtering only**: given an authenticated user,
return the vendor tools they are allowed to bind to an agent.

    * ``vendor_admin`` → every registered tool.
    * ``solo_user``     → tools flagged ``is_global``.
    * ``tenant_user`` / ``tenant_admin`` → ``is_global`` tools **plus** tools
      granted to the caller's tenant via ``tenant_resource_grants``.

Semantic similarity matching (embed the NL query, rank the filtered set) is
deferred to a later phase; :func:`get_authorized_vendor_catalog_semantic` is
the intentional seam and currently raises ``NotImplementedError``.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.roles import Roles

from vendor_resources.models import TenantResourceGrant, ToolEmbedding, VendorTool
from vendor_resources.services.embeddings import cosine_similarity, embed_text


async def get_authorized_vendor_catalog(
    db: AsyncSession, *, user: CurrentUser
) -> list[VendorTool]:
    """Return the tools the calling user is authorised to use (access-filtered)."""
    if user.role == Roles.VENDOR_ADMIN:
        result = await db.execute(select(VendorTool).order_by(VendorTool.name))
        return list(result.scalars().all())

    if user.role == Roles.SOLO_USER:
        result = await db.execute(
            select(VendorTool)
            .where(VendorTool.is_global.is_(True))
            .order_by(VendorTool.name)
        )
        return list(result.scalars().all())

    # tenant_user / tenant_admin: globals + granted-to-my-tenant
    grant_subq = select(TenantResourceGrant.resource_id).where(
        TenantResourceGrant.tenant_id == user.tenant_id,
        TenantResourceGrant.resource_type == "vendor_tool",
    )
    result = await db.execute(
        select(VendorTool)
        .where(
            or_(
                VendorTool.is_global.is_(True),
                VendorTool.id.in_(grant_subq),
            )
        )
        .order_by(VendorTool.name)
    )
    return list(result.scalars().all())


async def get_authorized_vendor_catalog_semantic(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    top_k: int = 5,
    embedding_provider: Optional[str] = None,
) -> list[VendorTool]:
    """Semantic match: rank the access-filtered catalog against ``query``.

    Access control is enforced **first** (via :func:`get_authorized_vendor_catalog`),
    then the candidate tools are ranked by cosine similarity between the query
    embedding and each tool's stored ``ToolEmbedding``. Tools without an
    embedding (or with a mismatched dimension) are skipped. If no embeddings are
    available or the query can't be embedded, falls back to the access-filtered
    list truncated to ``top_k``.
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
        e.tool_id: e
        for e in (
            await db.execute(
                select(ToolEmbedding).where(ToolEmbedding.tool_id.in_(candidate_ids))
            )
        ).scalars().all()
    }

    scored: list[tuple[float, VendorTool]] = []
    for tool in candidates:
        emb = emap.get(tool.id)
        if emb is None or emb.dim != len(q_vec):
            continue  # no embedding or mixed model — skip neutrally
        scored.append((cosine_similarity(q_vec, emb.embedding), tool))

    if not scored:
        return candidates[:top_k]

    scored.sort(key=lambda s: s[0], reverse=True)
    return [tool for _, tool in scored[:top_k]]


__all__ = [
    "get_authorized_vendor_catalog",
    "get_authorized_vendor_catalog_semantic",
]