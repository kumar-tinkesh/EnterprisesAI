"""MCP Server Management & Registration endpoints (Admin)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor.api.v1.schemas import (
    AddMCPServerRequest,
    AddMCPServerResponse,
    ConnectMCPServerRequest,
    MCPServerResponse,
)
from vendor.services.mcp_service import (
    add_mcp_server,
    create_mcp_server,
    delete_mcp_server,
    list_mcp_servers,
)

logger = logging.getLogger("vendor.servers")

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


# Step 1: Add MCP Server (Register only — no connection)
@router.post(
    "/mcp",
    response_model=AddMCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_add_mcp_server(
    payload: AddMCPServerRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Step 1: Add an MCP server from a Remote MCP URL or GitHub/Source repository URL."""
    server = await add_mcp_server(db, data=payload, actor_id=user.id)
    await db.commit()
    await db.refresh(server)
    return server


# Legacy endpoint (kept for backward compatibility)
@router.post(
    "/mcp/legacy",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_create_mcp_server_legacy(
    payload: ConnectMCPServerRequest,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Legacy: Register an MCP server with optional immediate connection."""
    server = await create_mcp_server(db, data=payload, actor_id=user.id)
    await db.commit()
    await db.refresh(server)
    return server


@router.get("/mcp", response_model=list[MCPServerResponse])
async def get_list_mcp_servers(
    _user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    return await list_mcp_servers(db)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server_endpoint(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_mcp_server(db, server_id=server_id, actor_id=user.id)
    if not deleted:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await db.commit()
    return None
