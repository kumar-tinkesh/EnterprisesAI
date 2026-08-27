"""Vendor management & platform stats service."""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.roles import Roles
from src.core.security import hash_password
from src.models import Tenant, User, VendorUser
from src.models.workspace import Workspace, WorkspaceMember
from src.api.v1.vendor.schemas import (
    VendorStats,
    VendorTenantCreate,
    VendorTenantOut,
    VendorTenantUpdate,
)


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


async def _unique_tenant_slug(db: AsyncSession, base: str) -> str:
    base = _slugify(base)
    candidate = base
    n = 2
    while True:
        row = (
            await db.execute(select(Tenant.id).where(Tenant.slug == candidate))
        ).scalars().first()
        if row is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def get_vendor_stats(db: AsyncSession) -> VendorStats:
    total_tenants = (
        await db.execute(
            select(func.count(Tenant.id)).where(Tenant.is_personal.is_(False))
        )
    ).scalar_one()

    individual_users = (
        await db.execute(
            select(func.count(User.id)).where(User.role == Roles.SOLO_USER)
        )
    ).scalar_one()

    user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    vendor_count = (await db.execute(select(func.count(VendorUser.id)))).scalar_one()
    total_users = user_count + vendor_count

    total_workspaces = (await db.execute(select(func.count(Workspace.id)))).scalar_one()

    return VendorStats(
        total_tenants=total_tenants,
        individual_users=individual_users,
        total_users=total_users,
        total_workspaces=total_workspaces,
    )


async def list_vendor_tenants(db: AsyncSession) -> list[VendorTenantOut]:
    tenants = list(
        (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars()
    )

    result: list[VendorTenantOut] = []
    for t in tenants:
        admin = (
            await db.execute(
                select(User).where(User.tenant_id == t.id).order_by(User.created_at)
            )
        ).scalars().first()

        u_count = (
            await db.execute(
                select(func.count(User.id)).where(User.tenant_id == t.id)
            )
        ).scalar_one()

        w_count = (
            await db.execute(
                select(func.count(Workspace.id)).where(Workspace.tenant_id == t.id)
            )
        ).scalar_one()

        result.append(
            VendorTenantOut(
                id=t.id,
                name=t.name,
                slug=t.slug,
                status=t.status,
                is_personal=t.is_personal,
                created_at=t.created_at,
                admin_email=admin.email if admin else None,
                admin_name=admin.full_name if admin else None,
                user_count=u_count,
                workspace_count=w_count,
            )
        )

    return result


async def create_vendor_tenant(
    db: AsyncSession, data: VendorTenantCreate
) -> VendorTenantOut:
    admin_email = data.admin_email.lower()
    existing_user = (
        await db.execute(select(User).where(User.email == admin_email))
    ).scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Admin email already registered"
        )

    slug_candidate = data.slug or _slugify(data.name)
    slug = await _unique_tenant_slug(db, slug_candidate)

    tenant = Tenant(name=data.name, slug=slug, is_personal=False)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=admin_email,
        hashed_password=hash_password(data.admin_password),
        full_name=data.admin_full_name,
        role=Roles.TENANT_ADMIN,
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    workspace = Workspace(
        tenant_id=tenant.id,
        name=f"{tenant.name} Workspace",
        slug=_slugify(f"{slug}-ws"),
    )
    db.add(workspace)
    await db.flush()

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    await db.commit()
    await db.refresh(tenant)

    return VendorTenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        is_personal=tenant.is_personal,
        created_at=tenant.created_at,
        admin_email=user.email,
        admin_name=user.full_name,
        user_count=1,
        workspace_count=1,
    )


async def update_vendor_tenant(
    db: AsyncSession, tenant_id: str, data: VendorTenantUpdate
) -> VendorTenantOut:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    if data.name is not None:
        tenant.name = data.name
    if data.status is not None:
        tenant.status = data.status

    await db.commit()
    await db.refresh(tenant)

    admin = (
        await db.execute(
            select(User).where(User.tenant_id == tenant.id).order_by(User.created_at)
        )
    ).scalars().first()

    u_count = (
        await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant.id)
        )
    ).scalar_one()

    w_count = (
        await db.execute(
            select(func.count(Workspace.id)).where(Workspace.tenant_id == tenant.id)
        )
    ).scalar_one()

    return VendorTenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        is_personal=tenant.is_personal,
        created_at=tenant.created_at,
        admin_email=admin.email if admin else None,
        admin_name=admin.full_name if admin else None,
        user_count=u_count,
        workspace_count=w_count,
    )


async def delete_vendor_tenant(db: AsyncSession, tenant_id: str) -> None:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    users = list(
        (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()
    )
    for u in users:
        await db.delete(u)

    await db.delete(tenant)
    await db.commit()
