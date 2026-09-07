"""End-User Self-Service Connection & Disconnect endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from vendor.api.v1.schemas import (
    ConnectCredentialsRequest,
    ConnectMCPServerResponse,
)
from vendor.services.mcp_auth import McpAuthError
from vendor.services.mcp_service import (
    disconnect_user_credential,
    get_mcp_server,
    is_server_visible_to_user,
    verify_user_credentials,
)

logger = logging.getLogger("vendor.user_connection")

router = APIRouter()


@router.post("/mcp/{server_id}/connect-as-user", response_model=ConnectMCPServerResponse)
async def connect_mcp_server_as_user_endpoint(
    server_id: str,
    payload: ConnectCredentialsRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End-user self-service connect: store *this user's own* credentials for an already vendor-verified server."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None or not await is_server_visible_to_user(db, user=user, server=server):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    if server.status != "VERIFIED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This server hasn't been verified by the vendor yet",
        )
    try:
        result = await verify_user_credentials(
            db,
            server=server,
            user_id=user.id,
            tenant_id=user.tenant_id,
            request_credentials=payload.credentials or {},
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
        logger.exception(
            "Failed to connect user %s to MCP server %s", user.id, server_id
        )

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
            err_msg = "MCP server process exited (connection closed). Please verify your credentials."

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Connection failed: {err_msg}",
        ) from exc
    return ConnectMCPServerResponse(
        transport=result["transport"],
        bound_tools=result["tool_names"],
        tools=[],
        auth_type=result.get("auth_type", "none"),
        status="CONNECTED",
    )


@router.post("/mcp/{server_id}/disconnect-as-user", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_mcp_server_as_user_endpoint(
    server_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End-user self-service disconnect: remove only the calling user's own isolated credential."""
    server = await get_mcp_server(db, server_id=server_id)
    if server is None or not await is_server_visible_to_user(db, user=user, server=server):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    await disconnect_user_credential(db, server_id=server_id, user_id=user.id)
    await db.commit()
