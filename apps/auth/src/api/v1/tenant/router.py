"""Tenant & member management endpoints for Tenant Admins."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db
from src.api.v1.tenant import schemas as sc
from src.api.v1.tenant.service import (
    create_tenant,
    create_tenant_member,
    delete_tenant_member,
    get_tenant_stats,
    list_tenant_members,
    list_tenants,
    update_tenant_member,
)

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.post("", response_model=sc.TenantOut, status_code=201)
async def post_tenant(
    payload: sc.TenantCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await create_tenant(db, name=payload.name, slug=payload.slug)


@router.get("", response_model=list[sc.TenantOut])
async def get_tenants(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await list_tenants(db)


# ── Tenant Admin Member & Stats endpoints ──────────────────────────────────

@router.get("/stats", response_model=sc.TenantStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    return await get_tenant_stats(db, tenant_id=current.tenant_id or "")


@router.get("/members", response_model=list[sc.MemberOut])
async def get_members(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    return await list_tenant_members(db, tenant_id=current.tenant_id or "")


@router.post("/members", response_model=sc.MemberOut, status_code=201)
async def post_member(
    payload: sc.MemberCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    return await create_tenant_member(db, tenant_id=current.tenant_id or "", data=payload)


@router.patch("/members/{member_id}", response_model=sc.MemberOut)
async def patch_member(
    member_id: str,
    payload: sc.MemberUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    return await update_tenant_member(
        db, tenant_id=current.tenant_id or "", member_id=member_id, data=payload
    )


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    member_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    await delete_tenant_member(
        db,
        tenant_id=current.tenant_id or "",
        member_id=member_id,
        current_user_id=current.id,
    )