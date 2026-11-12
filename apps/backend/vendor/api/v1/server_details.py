"""What the admin's Apps page shows about each MCP server (vendor admin only).

    GET    /mcp/overview                      per server: people connected, tools, tenants granted
    GET    /mcp/{server_id}/details           its tools (with what each can do, and whether it's on),
                                              people connected, tenants granted, when it was last tested
    PUT    /mcp/{server_id}/disabled-tools    {"names": [...]}: the tools nobody may use (vendor.services.tool_access)
    DELETE /mcp/{server_id}/grants/{tenant_id} take a granted server back from a tenant

Counts only — never anyone's credentials.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db
from src.models.auth import AuditEvent
from src.models.tenant import Tenant

from vendor.models import MCPTool, TenantResourceGrant, VendorMCPCredential
from vendor.services.mcp_service import get_mcp_server
from vendor.services.tool_access import disabled_tools

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


class ServerCounts(BaseModel):
    id: str
    users_connected: int
    tools: int
    tenants_granted: int


class ToolInfo(BaseModel):
    name: str
    description: str
    # read | edit | delete — what the builder's approval step treats it as
    risk: str
    # False: the admin turned it off; agents never get it.
    on: bool = True


class GrantInfo(BaseModel):
    tenant_id: str
    name: str


class ServerDetails(BaseModel):
    id: str
    users_connected: int
    tools: list[ToolInfo]
    grants: list[GrantInfo]
    last_tested_at: datetime | None


async def _counts(db: AsyncSession, column, where=None) -> dict[str, int]:
    query = select(column, func.count()).group_by(column)
    if where is not None:
        query = query.where(where)
    return {k: n for k, n in (await db.execute(query)).all() if k}


@router.get("/mcp/overview", response_model=list[ServerCounts])
async def mcp_overview(_user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    users = await _counts(db, VendorMCPCredential.server_id, VendorMCPCredential.user_id.is_not(None))
    tools = await _counts(db, MCPTool.mcp_server_id)
    grants = await _counts(db, TenantResourceGrant.resource_id, TenantResourceGrant.resource_type == "mcp")
    ids = set(users) | set(tools) | set(grants)
    return [ServerCounts(id=i, users_connected=users.get(i, 0), tools=tools.get(i, 0), tenants_granted=grants.get(i, 0)) for i in sorted(ids)]


@router.get("/mcp/{server_id}/details", response_model=ServerDetails)
async def mcp_details(server_id: str, _user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    from builder.services.tool_runtime import classify_tool

    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    tools = (await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server_id).order_by(MCPTool.name))).scalars().all()
    users = (
        await db.execute(
            select(func.count()).select_from(VendorMCPCredential)
            .where(VendorMCPCredential.server_id == server_id, VendorMCPCredential.user_id.is_not(None))
        )
    ).scalar_one()
    grants = (
        await db.execute(
            select(Tenant.id, Tenant.name)
            .join(TenantResourceGrant, TenantResourceGrant.tenant_id == Tenant.id)
            .where(TenantResourceGrant.resource_type == "mcp", TenantResourceGrant.resource_id == server_id)
            .order_by(Tenant.name)
        )
    ).all()
    tested = (
        await db.execute(
            select(func.max(AuditEvent.created_at))
            .where(AuditEvent.action == "mcp_server.test_connection", AuditEvent.resource == f"mcp_server:{server_id}")
        )
    ).scalar_one()
    off = disabled_tools(server)
    return ServerDetails(
        id=server_id,
        users_connected=users,
        tools=[
            ToolInfo(name=t.name, description=t.description or "", risk=classify_tool(t.name, t.annotations).risk, on=t.name not in off)
            for t in tools
        ],
        grants=[GrantInfo(tenant_id=i, name=n) for i, n in grants],
        last_tested_at=tested,
    )


@router.delete("/mcp/{server_id}/grants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(server_id: str, tenant_id: str, _user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        delete(TenantResourceGrant).where(
            TenantResourceGrant.resource_type == "mcp", TenantResourceGrant.resource_id == server_id,
            TenantResourceGrant.tenant_id == tenant_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That tenant doesn't have this server.")
    await db.commit()


class DisabledTools(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=500)


@router.put("/mcp/{server_id}/disabled-tools", response_model=DisabledTools)
async def set_disabled_tools(server_id: str, payload: DisabledTools, _user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    names = sorted({n.strip() for n in payload.names if n.strip()})
    server.auth_config = {**(server.auth_config or {}), "disabled_tools": names}
    await db.commit()
    return DisabledTools(names=names)
