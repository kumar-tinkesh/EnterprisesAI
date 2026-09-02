"""MCP server management service."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.audit import log_audit_event
from src.models.tenant import Tenant

# Ensure vendor_resources is importable (same approach as main.py)
ROOT = Path(__file__).resolve().parents[6]  # EnterpriseAI/ (file is at EnterpriseAI/apps/auth/src/api/v1/mcp/service.py)
for _p in (ROOT, ROOT / "apps" / "auth", ROOT / "apps" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vendor_resources.models import VendorMCPServer, TenantResourceGrant  # noqa: E402


class McpServerService:
    """Service for managing MCP servers with tenant-based access control."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_server(
        self,
        *,
        name: str,
        description: str,
        transport: str,
        server_url: str,
        bound_tools: list[dict[str, Any]] | None = None,
        is_global: bool = False,
        current_user: CurrentUser,
    ) -> VendorMCPServer:
        """Create a new MCP server (vendor admin only)."""
        if current_user.role != "vendor_admin":
            raise ValueError("Only vendor admins can create MCP servers")

        # Auto-discover tools if not provided
        if bound_tools is None:
            bound_tools = await self._discover_tools(server_url, transport)

        server = VendorMCPServer(
            name=name,
            description=description,
            transport=transport,
            server_url=str(server_url),
            bound_tools=bound_tools,
            is_global=is_global,
        )

        self.db.add(server)
        await self.db.commit()
        await self.db.refresh(server)

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_server_created",
            details={"server_id": server.id, "name": server.name, "is_global": is_global},
        )

        return server

    async def list_servers(
        self,
        *,
        current_user: CurrentUser,
        include_inaccessible: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VendorMCPServer]:
        """List MCP servers based on user access."""
        
        if current_user.role == "vendor_admin":
            # Vendor admins see all servers
            stmt = (
                select(VendorMCPServer)
                .limit(limit)
                .offset(offset)
                .order_by(VendorMCPServer.name)
            )
        else:
            # Regular users see global servers + granted servers
            if include_inaccessible:
                # Show all servers but mark accessibility
                stmt = (
                    select(VendorMCPServer)
                    .limit(limit)
                    .offset(offset)
                    .order_by(VendorMCPServer.name)
                )
            else:
                # Only accessible servers
                stmt = (
                    select(VendorMCPServer)
                    .where(
                        or_(
                            VendorMCPServer.is_global == True,
                            VendorMCPServer.id.in_(
                                select(TenantResourceGrant.resource_id).where(
                                    and_(
                                        TenantResourceGrant.tenant_id == current_user.tenant_id,
                                        TenantResourceGrant.resource_type == "mcp_server",
                                    )
                                )
                            ),
                        )
                    )
                    .limit(limit)
                    .offset(offset)
                    .order_by(VendorMCPServer.name)
                )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_server(
        self,
        server_id: str,
        *,
        current_user: CurrentUser,
    ) -> VendorMCPServer | None:
        """Get a specific MCP server if user has access."""
        stmt = select(VendorMCPServer).where(VendorMCPServer.id == server_id)
        
        result = await self.db.execute(stmt)
        server = result.scalar_one_or_none()
        
        if not server:
            return None

        # Check access
        if not await self._has_server_access(server, current_user):
            return None

        return server

    async def update_server(
        self,
        server_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        transport: str | None = None,
        server_url: str | None = None,
        bound_tools: list[dict[str, Any]] | None = None,
        is_global: bool | None = None,
        current_user: CurrentUser,
    ) -> VendorMCPServer | None:
        """Update MCP server (vendor admin only)."""
        if current_user.role != "vendor_admin":
            raise ValueError("Only vendor admins can update MCP servers")

        stmt = select(VendorMCPServer).where(VendorMCPServer.id == server_id)
        result = await self.db.execute(stmt)
        server = result.scalar_one_or_none()
        
        if not server:
            return None

        # Update fields
        if name is not None:
            server.name = name
        if description is not None:
            server.description = description
        if transport is not None:
            server.transport = transport
        if server_url is not None:
            server.server_url = server_url
        if bound_tools is not None:
            server.bound_tools = bound_tools
        if is_global is not None:
            server.is_global = is_global

        await self.db.commit()
        await self.db.refresh(server)

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_server_updated",
            details={"server_id": server.id, "name": server.name},
        )

        return server

    async def delete_server(
        self,
        server_id: str,
        *,
        current_user: CurrentUser,
    ) -> bool:
        """Delete MCP server (vendor admin only)."""
        if current_user.role != "vendor_admin":
            raise ValueError("Only vendor admins can delete MCP servers")

        stmt = select(VendorMCPServer).where(VendorMCPServer.id == server_id)
        result = await self.db.execute(stmt)
        server = result.scalar_one_or_none()
        
        if not server:
            return False

        server_name = server.name
        await self.db.delete(server)
        await self.db.commit()

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_server_deleted",
            details={"server_id": server_id, "name": server_name},
        )

        return True

    async def grant_server_access(
        self,
        server_id: str,
        tenant_id: str,
        *,
        current_user: CurrentUser,
    ) -> TenantResourceGrant:
        """Grant tenant access to MCP server (vendor admin only)."""
        if current_user.role != "vendor_admin":
            raise ValueError("Only vendor admins can grant server access")

        # Check if server exists
        stmt = select(VendorMCPServer).where(VendorMCPServer.id == server_id)
        result = await self.db.execute(stmt)
        server = result.scalar_one_or_none()
        if not server:
            raise ValueError("MCP server not found")

        # Check if tenant exists
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise ValueError("Tenant not found")

        # Check if grant already exists
        stmt = select(TenantResourceGrant).where(
            and_(
                TenantResourceGrant.tenant_id == tenant_id,
                TenantResourceGrant.resource_type == "mcp_server",
                TenantResourceGrant.resource_id == server_id,
            )
        )
        result = await self.db.execute(stmt)
        existing_grant = result.scalar_one_or_none()
        if existing_grant:
            raise ValueError("Grant already exists")

        grant = TenantResourceGrant(
            tenant_id=tenant_id,
            resource_type="mcp_server",
            resource_id=server_id,
        )

        self.db.add(grant)
        await self.db.commit()
        await self.db.refresh(grant)

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_server_access_granted",
            details={
                "server_id": server_id,
                "tenant_id": tenant_id,
                "grant_id": grant.id,
            },
        )

        return grant

    async def revoke_server_access(
        self,
        server_id: str,
        tenant_id: str,
        *,
        current_user: CurrentUser,
    ) -> bool:
        """Revoke tenant access to MCP server (vendor admin only)."""
        if current_user.role != "vendor_admin":
            raise ValueError("Only vendor admins can revoke server access")

        stmt = select(TenantResourceGrant).where(
            and_(
                TenantResourceGrant.tenant_id == tenant_id,
                TenantResourceGrant.resource_type == "mcp_server",
                TenantResourceGrant.resource_id == server_id,
            )
        )
        result = await self.db.execute(stmt)
        grant = result.scalar_one_or_none()

        if not grant:
            return False

        await self.db.delete(grant)
        await self.db.commit()

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_server_access_revoked",
            details={
                "server_id": server_id,
                "tenant_id": tenant_id,
                "grant_id": grant.id,
            },
        )

        return True

    async def _has_server_access(
        self,
        server: VendorMCPServer,
        user: CurrentUser,
    ) -> bool:
        """Check if user has access to server."""
        if user.role == "vendor_admin":
            return True
            
        if server.is_global:
            return True

        # Check tenant grants
        stmt = select(TenantResourceGrant).where(
            and_(
                TenantResourceGrant.tenant_id == user.tenant_id,
                TenantResourceGrant.resource_type == "mcp_server",
                TenantResourceGrant.resource_id == server.id,
            )
        )
        result = await self.db.execute(stmt)
        grant = result.scalar_one_or_none()
        
        return grant is not None

    async def _discover_tools(
        self,
        server_url: str,
        transport: str,
    ) -> list[dict[str, Any]]:
        """Auto-discover tools from MCP server."""
        try:
            if transport == "sse":
                # For SSE transport, try to get tools list
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{server_url}/tools")
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict) and "tools" in data:
                            return data["tools"]
                        elif isinstance(data, list):
                            return data
            # For stdio or failed discovery, return empty list
            return []
        except Exception:
            # If discovery fails, return empty list
            return []