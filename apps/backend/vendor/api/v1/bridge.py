"""End-user self-service lifecycle for native device-pairing bridges (e.g.
WhatsApp) — see vendor.services.whatsapp_bridge.manager for why this can't
be a plain credential POST like connect-as-user."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from vendor.api.v1.schemas import BridgeStatusResponse
from vendor.services.mcp_service import get_mcp_server, is_server_visible_to_user
from vendor.services.whatsapp_bridge import manager as bridge_manager

logger = logging.getLogger("vendor.bridge")

router = APIRouter()


def _is_device_pairing(server) -> bool:
    return ((server.auth_config or {}).get("auth_type") or "").lower() == "device_pairing"


async def _get_visible_device_pairing_server(db, *, server_id: str, user: CurrentUser):
    server = await get_mcp_server(db, server_id=server_id)
    if server is None or not await is_server_visible_to_user(db, user=user, server=server):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    if not _is_device_pairing(server):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This server doesn't use device pairing — connect with connect-as-user instead",
        )
    if server.status != "VERIFIED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This server hasn't been verified by the vendor yet",
        )
    return server


@router.post("/mcp/{server_id}/bridge/connect-as-user", response_model=BridgeStatusResponse)
async def start_bridge_as_user(
    server_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start (or resume) *this user's own* bridge process. Returns
    immediately with a status — poll status-as-user for progress (the QR
    code, once available, or the final connected/error state)."""
    server = await _get_visible_device_pairing_server(db, server_id=server_id, user=user)
    try:
        result = await bridge_manager.start_bridge(
            db, server=server, user_id=user.id, tenant_id=user.tenant_id
        )
    except bridge_manager.BridgeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return BridgeStatusResponse(**result)


@router.get("/mcp/{server_id}/bridge/status-as-user", response_model=BridgeStatusResponse)
async def get_bridge_status_as_user(
    server_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll this user's own bridge status — call this every ~2s while
    'starting'/'awaiting_qr' until it settles at 'connected' or 'error'."""
    await _get_visible_device_pairing_server(db, server_id=server_id, user=user)
    result = await bridge_manager.get_status(db, server_id=server_id, user_id=user.id)
    return BridgeStatusResponse(**result)


@router.post("/mcp/{server_id}/bridge/disconnect-as-user", status_code=status.HTTP_204_NO_CONTENT)
async def stop_bridge_as_user(
    server_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop this user's bridge process but keep its authenticated session —
    a future connect reconnects instantly with no new QR, matching closing
    (not unlinking) a real WhatsApp Linked Device."""
    await _get_visible_device_pairing_server(db, server_id=server_id, user=user)
    await bridge_manager.stop_bridge(db, server_id=server_id, user_id=user.id, wipe=False)


@router.post("/mcp/{server_id}/bridge/forget-as-user", status_code=status.HTTP_204_NO_CONTENT)
async def forget_bridge_as_user(
    server_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop this user's bridge process *and* wipe its session — a future
    connect always requires a fresh QR scan, matching unlinking the device
    from the WhatsApp app on the phone."""
    await _get_visible_device_pairing_server(db, server_id=server_id, user=user)
    await bridge_manager.stop_bridge(db, server_id=server_id, user_id=user.id, wipe=True)
