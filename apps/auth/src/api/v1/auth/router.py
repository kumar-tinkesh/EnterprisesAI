"""Unified auth API endpoints (signup / login / refresh / logout / me)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.api.schemas import MessageResponse
from src.db.session import get_db
from src.api.v1.auth import schemas as sc
from src.api.v1.auth.service import (
    login as svc_login,
    logout as svc_logout,
    refresh_tokens,
    signup as svc_signup,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _resolve_role(row) -> str:
    return getattr(row, "role", "tenant_user")


@router.post(
    "/signup", response_model=sc.AuthResponse, status_code=status.HTTP_201_CREATED
)
async def signup(payload: sc.SignupRequest, db: AsyncSession = Depends(get_db)):
    account, tokens = await svc_signup(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
        tenant_name=payload.tenant_name,
    )
    return sc.AuthResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user=sc.AccountOut(
            id=account.id,
            email=account.email,
            full_name=account.full_name,
            role=_resolve_role(account),
            tenant_id=getattr(account, "tenant_id", None),
        ),
    )


@router.post("/login", response_model=sc.AuthResponse)
async def login(payload: sc.LoginRequest, db: AsyncSession = Depends(get_db)):
    account, tokens = await svc_login(
        db,
        email=payload.email,
        password=payload.password,
        role=payload.role,
        workspace_id=payload.workspace_id,
    )
    return sc.AuthResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user=sc.AccountOut(
            id=account.id,
            email=account.email,
            full_name=account.full_name,
            role=_resolve_role(account),
            tenant_id=getattr(account, "tenant_id", None),
        ),
    )


@router.post("/refresh", response_model=dict)
async def refresh(payload: sc.RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await refresh_tokens(db, refresh_token=payload.refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: sc.RefreshRequest, db: AsyncSession = Depends(get_db)):
    await svc_logout(db, refresh_token=payload.refresh_token)
    return MessageResponse(detail="Logged out")


@router.get("/me", response_model=sc.MeResponse)
async def me(current: CurrentUser = Depends(get_current_user)):
    return sc.MeResponse(
        id=current.id,
        email=current.email,
        full_name=current.full_name,
        role=current.role,
        tenant_id=current.tenant_id,
        is_active=current.is_active,
    )


@router.get("/audit-logs", response_model=list[sc.AuditEventOut])
async def list_audit_logs(
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    from src.core.audit import get_audit_events

    # For tenant users/admins, scope audit events to their tenant_id. Vendor admins can view all.
    tenant_id = current.tenant_id if current.role != "vendor_admin" else None
    user_id = current.id if current.role == "tenant_user" else None
    return await get_audit_events(
        db, tenant_id=tenant_id, user_id=user_id, action=action, limit=limit, offset=offset
    )

