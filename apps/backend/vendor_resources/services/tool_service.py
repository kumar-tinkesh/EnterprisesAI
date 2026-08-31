"""Vendor Tool CRUD + tenant grant business logic.

Each mutating service records a security audit event (via the reused
``src.core.audit.log_audit_event``) and flushes; the **caller** commits so the
entity and its audit row persist atomically.

Tool creation also best-effort embeds the tool's ``name + description`` for the
semantic catalog matcher. Embedding failures never break tool creation — the
tool is still stored and the admin can (re)embed later via :func:`embed_tool`.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event
from src.models import Tenant

from vendor_resources.models import TenantResourceGrant, ToolEmbedding, VendorTool
from vendor_resources.schemas import CreateVendorToolRequest, GrantTenantResourceRequest
from vendor_resources.services.embeddings import embed_tool_text

logger = logging.getLogger("vendor_resources.tool_service")

# resource_type values that the grant table currently knows how to validate.
_GRANTABLE_RESOURCE_TYPES = {"vendor_tool"}


async def _upsert_tool_embedding(
    db: AsyncSession, *, tool_id: str, vector: list[float], model: str
) -> None:
    """Insert or replace a tool's embedding row. Caller commits."""
    existing = (
        await db.execute(select(ToolEmbedding).where(ToolEmbedding.tool_id == tool_id))
    ).scalars().first()
    if existing is not None:
        existing.embedding = list(vector)
        existing.model = model
        existing.dim = len(vector)
        return
    db.add(
        ToolEmbedding(
            tool_id=tool_id,
            embedding=list(vector),
            model=model,
            dim=len(vector),
        )
    )


async def create_tool(
    db: AsyncSession, *, data: CreateVendorToolRequest, actor_id: str
) -> VendorTool:
    """Insert a new vendor tool, audit the creation, and best-effort embed it.

    Caller commits. Embedding failures are logged and never break creation.
    """
    tool = VendorTool(
        name=data.name,
        description=data.description,
        category=data.category,
        method=data.method,
        endpoint_url=data.endpoint_url,
        parameters_schema=data.parameters_schema,
        is_global=data.is_global,
        vault_secret_ref=data.vault_secret_ref,
    )
    db.add(tool)
    await db.flush()
    await log_audit_event(
        db,
        action="vendor_tool.create",
        user_id=actor_id,
        resource=f"vendor_tool:{tool.id}",
        detail=f"name={tool.name}",
    )

    # Best-effort semantic embedding — never fail tool creation over this.
    try:
        embedded = await embed_tool_text(tool)
        if embedded is not None:
            vector, model = embedded
            await _upsert_tool_embedding(db, tool_id=tool.id, vector=vector, model=model)
            await db.flush()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("best-effort embedding failed for tool %s: %s", tool.id, exc)

    return tool


async def embed_tool(
    db: AsyncSession, *, tool_id: str, actor_id: str
) -> bool:
    """(Re)embed an existing tool on demand. Caller commits.

    Returns True if the tool was found and (re)embedded, False if the tool
    does not exist. If the gateway is unavailable the existing embedding (if
    any) is left untouched and False-via-no-embed is reported as True-with-warning
    — specifically: returns True when the tool exists, even if embedding was
    skipped due to no provider.
    """
    tool = await get_tool(db, tool_id)
    if tool is None:
        return False

    embedded = await embed_tool_text(tool)
    if embedded is not None:
        vector, model = embedded
        await _upsert_tool_embedding(db, tool_id=tool.id, vector=vector, model=model)
        await db.flush()
    else:
        logger.warning("embed_tool skipped (no embedding produced) for tool %s", tool_id)

    await log_audit_event(
        db,
        action="vendor_tool.embed",
        user_id=actor_id,
        resource=f"vendor_tool:{tool_id}",
    )
    return True


async def list_tools(db: AsyncSession) -> list[VendorTool]:
    """Return all registered vendor tools (admin view)."""
    result = await db.execute(select(VendorTool).order_by(VendorTool.created_at.desc()))
    return list(result.scalars().all())


async def get_tool(db: AsyncSession, tool_id: str) -> Optional[VendorTool]:
    """Return a single tool by id, or None."""
    result = await db.execute(select(VendorTool).where(VendorTool.id == tool_id))
    return result.scalars().first()


async def delete_tool(
    db: AsyncSession, *, tool_id: str, actor_id: str
) -> bool:
    """Delete a tool and cascade-delete its tenant grants. Caller commits.

    Returns True if a tool was deleted, False if it did not exist.
    """
    tool = await get_tool(db, tool_id)
    if tool is None:
        return False

    # Cascade: revoke any grants pointing at this tool.
    await db.execute(
        delete(TenantResourceGrant).where(
            TenantResourceGrant.resource_id == tool_id,
            TenantResourceGrant.resource_type == "vendor_tool",
        )
    )
    await db.delete(tool)
    await db.flush()
    await log_audit_event(
        db,
        action="vendor_tool.delete",
        user_id=actor_id,
        resource=f"vendor_tool:{tool_id}",
    )
    return True


async def grant_resource(
    db: AsyncSession, *, data: GrantTenantResourceRequest, actor_id: str
) -> tuple[TenantResourceGrant, bool]:
    """Grant a resource to a tenant.

    Validates that the tenant and resource exist. Idempotent: a duplicate
    grant returns the existing row (created=False) instead of erroring.

    Returns ``(grant, created)``. Caller commits.
    """
    if data.resource_type not in _GRANTABLE_RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource_type: {data.resource_type}")

    # Validate tenant exists.
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == data.tenant_id))
    ).scalars().first()
    if tenant is None:
        raise LookupError(f"Tenant not found: {data.tenant_id}")

    # Validate resource exists (Phase 1: only vendor_tool).
    if data.resource_type == "vendor_tool":
        resource = await get_tool(db, data.resource_id)
        if resource is None:
            raise LookupError(f"Vendor tool not found: {data.resource_id}")

    # Idempotent upsert — check existing first to avoid IntegrityError.
    existing = (
        await db.execute(
            select(TenantResourceGrant).where(
                TenantResourceGrant.tenant_id == data.tenant_id,
                TenantResourceGrant.resource_type == data.resource_type,
                TenantResourceGrant.resource_id == data.resource_id,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing, False

    grant = TenantResourceGrant(
        tenant_id=data.tenant_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
    )
    db.add(grant)
    try:
        await db.flush()
    except IntegrityError as exc:  # race: another request inserted the same row
        await db.rollback()
        existing = (
            await db.execute(
                select(TenantResourceGrant).where(
                    TenantResourceGrant.tenant_id == data.tenant_id,
                    TenantResourceGrant.resource_type == data.resource_type,
                    TenantResourceGrant.resource_id == data.resource_id,
                )
            )
        ).scalars().first()
        if existing is None:
            raise exc
        return existing, False

    await log_audit_event(
        db,
        action="tenant_resource.grant",
        user_id=actor_id,
        tenant_id=data.tenant_id,
        resource=f"{data.resource_type}:{data.resource_id}",
    )
    return grant, True


__all__ = [
    "create_tool",
    "list_tools",
    "get_tool",
    "delete_tool",
    "embed_tool",
    "grant_resource",
]