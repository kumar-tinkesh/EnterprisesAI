"""Vendor admin endpoints for platform stats & tenant management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db
from src.api.v1.vendor import schemas as sc
from src.api.v1.vendor.service import (
    create_vendor_tenant,
    delete_vendor_tenant,
    get_vendor_stats,
    list_vendor_tenants,
    update_vendor_tenant,
)

router = APIRouter(prefix="/vendor", tags=["vendor"])


@router.get("/stats", response_model=sc.VendorStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await get_vendor_stats(db)


@router.get("/tenants", response_model=list[sc.VendorTenantOut])
async def get_tenants(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await list_vendor_tenants(db)


@router.post("/tenants", response_model=sc.VendorTenantOut, status_code=201)
async def post_tenant(
    payload: sc.VendorTenantCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await create_vendor_tenant(db, data=payload)


@router.patch("/tenants/{tenant_id}", response_model=sc.VendorTenantOut)
async def patch_tenant(
    tenant_id: str,
    payload: sc.VendorTenantUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return await update_vendor_tenant(db, tenant_id=tenant_id, data=payload)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    await delete_vendor_tenant(db, tenant_id=tenant_id)
