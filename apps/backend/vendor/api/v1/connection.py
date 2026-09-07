"""MCP Connection testing, Tool discovery, Embeddings, and Disconnect endpoints (Admin)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor.api.v1.schemas import (
    ConnectCredentialsRequest,
    ConnectMCPServerResponse,
    MCPServerResponse,
)
from vendor.models import MCPTool
from vendor.services.embedding import embed_server, embed_tool
from vendor.services.mcp_auth import McpAuthError
from vendor.services.mcp_service import (
    connect_registered_server,
    disconnect_mcp_server,
    get_mcp_server,
    test_mcp_connection,
)

logger = logging.getLogger("vendor.connection")

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


@router.post("/mcp/{server_id}/embed", status_code=status.HTTP_204_NO_CONTENT)
async def embed_mcp_server(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """(Re)compute a server's semantic embedding, and its tools' (admin)."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await embed_server(server)
    tools = (
        await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server.id))
    ).scalars().all()
    for tool in tools:
        await embed_tool(tool)
    await db.commit()
    return None


# Step 2: Test Connection & Discover Tools
@router.post(
    "/mcp/{server_id}/test",
    response_model=ConnectMCPServerResponse,
)
async def test_mcp_connection_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest | None = None,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Test connection and discover tools for a registered MCP server."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    if server.status == "VERIFIED":
        return ConnectMCPServerResponse(
            transport=getattr(server, "transport", "stdio"),
            bound_tools=server.bound_tools,
            tools=[],
            auth_type=server.auth_type or "none",
            status="VERIFIED",
        )
    try:
        creds = payload.credentials if payload is not None else None
        result = await test_mcp_connection(
            db, server=server, request_credentials=creds, tenant_id=user.id
        )
        await db.commit()
    except McpAuthError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential resolution failed: {exc}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to test MCP server %s", server_id)

        err_msg = str(exc)
        if isinstance(exc, BaseExceptionGroup):
            sub_msgs = []
            for sub in exc.exceptions:
                if isinstance(sub, BaseExceptionGroup):
                    sub_msgs.extend([str(s) for s in sub.exceptions])
                else:
                    sub_msgs.append(str(sub))
            err_msg = " | ".join(sub_msgs)

        if "Connection closed" in err_msg or "MCPError" in err_msg:
            err_msg = "MCP server process exited (connection closed). Please verify primary credentials and server command."

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Connection failed: {err_msg}",
        ) from exc
    return ConnectMCPServerResponse(**result)


# Legacy connect endpoint (kept for backward compatibility)
@router.post("/mcp/{server_id}/connect", response_model=ConnectMCPServerResponse)
async def connect_mcp_server_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest | None = None,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Legacy: Test connection and return discovered transport + tools."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    try:
        creds = payload.credentials if payload is not None else None
        result = await connect_registered_server(
            db, server=server, request_credentials=creds
        )
        await db.commit()
    except McpAuthError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential resolution failed: {exc}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to connect MCP server %s", server_id)

        err_msg = str(exc)
        if isinstance(exc, BaseExceptionGroup):
            sub_msgs = []
            for sub in exc.exceptions:
                if isinstance(sub, BaseExceptionGroup):
                    sub_msgs.extend([str(s) for s in sub.exceptions])
                else:
                    sub_msgs.append(str(sub))
            err_msg = " | ".join(sub_msgs)

        if "Connection closed" in err_msg or "MCPError" in err_msg:
            err_msg = "MCP server process exited (connection closed). Please verify primary credentials and server command."

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Connection failed: {err_msg}",
        ) from exc
    return ConnectMCPServerResponse(**result)


@router.post("/mcp/{server_id}/disconnect", response_model=MCPServerResponse)
async def disconnect_mcp_server_endpoint(
    server_id: str,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    """Disconnect an MCP server: reset status to UNCONNECTED and clear stored credentials."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    updated = await disconnect_mcp_server(db, server=server)
    await db.commit()
    await db.refresh(updated)
    return updated
