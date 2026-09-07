"""MCP server CRUD queries and visibility access control."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.audit import log_audit_event
from src.core.roles import Roles

from vendor.models import TenantResourceGrant, VendorMCPServer

logger = logging.getLogger("vendor.mcp_service")


async def list_mcp_servers(db: AsyncSession) -> list[VendorMCPServer]:
    """Return all registered MCP servers (admin view)."""
    result = await db.execute(select(VendorMCPServer).order_by(VendorMCPServer.created_at.desc()))
    return list(result.scalars().all())


async def get_mcp_server(db: AsyncSession, server_id: str) -> Optional[VendorMCPServer]:
    """Return a single MCP server by id, or None."""
    result = await db.execute(select(VendorMCPServer).where(VendorMCPServer.id == server_id))
    return result.scalars().first()


async def is_server_visible_to_user(
    db: AsyncSession, *, user: CurrentUser, server: VendorMCPServer
) -> bool:
    """Same access rule as ``user.services.catalog_engine.get_authorized_vendor_catalog``."""
    if user.role == Roles.VENDOR_ADMIN or server.is_global:
        return True
    if user.role == Roles.SOLO_USER:
        return False
    if not user.tenant_id:
        return False
    grant = (
        await db.execute(
            select(TenantResourceGrant.id).where(
                TenantResourceGrant.tenant_id == user.tenant_id,
                TenantResourceGrant.resource_type == "mcp",
                TenantResourceGrant.resource_id == server.id,
            )
        )
    ).scalars().first()
    return grant is not None


async def delete_mcp_server(
    db: AsyncSession, *, server_id: str, actor_id: str
) -> bool:
    """Delete an MCP server and cascade-delete its tenant grants."""
    server = await get_mcp_server(db, server_id)
    if server is None:
        return False

    from vendor.services import mcp_auth, mcp_service

    await db.execute(
        delete(TenantResourceGrant).where(
            TenantResourceGrant.resource_id == server_id,
            TenantResourceGrant.resource_type == "mcp",
        )
    )
    await mcp_auth.delete_server_credentials(db, server_id=server_id)
    mcp_auth.clear_token_cache(server_id)

    cleanup_fn = getattr(mcp_service, "_cleanup_server_local_repo_cache", None)
    if cleanup_fn:
        cleanup_fn(server)

    await db.delete(server)
    await db.flush()
    await log_audit_event(
        db,
        action="mcp_server.delete",
        user_id=actor_id,
 resource=f"mcp_server:{server_id}",
    )
    return True
