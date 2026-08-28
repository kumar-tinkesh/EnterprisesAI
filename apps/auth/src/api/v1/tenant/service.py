"""Tenant management & member service."""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.roles import Roles
from src.core.security import hash_password
from src.models import Tenant, User
from src.models.workspace import Workspace, WorkspaceMember
from src.api.v1.tenant.schemas import MemberCreate, MemberUpdate


async def get_tenant_stats(db: AsyncSession, tenant_id: str) -> dict[str, int]:
    ws_count = (
        await db.execute(
            select(func.count(Workspace.id)).where(Workspace.tenant_id == tenant_id)
        )
    ).scalar_one()

    mem_count = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id, User.role == Roles.TENANT_USER
            )
        )
    ).scalar_one()

    return {"workspace_count": ws_count, "member_count": mem_count}


async def list_tenant_members(db: AsyncSession, tenant_id: str) -> list[User]:
    return list(
        (
            await db.execute(
                select(User)
                .where(
                    User.tenant_id == tenant_id, User.role == Roles.TENANT_USER
                )
                .order_by(User.created_at)
            )
        ).scalars()
    )


async def create_tenant_member(
    db: AsyncSession, tenant_id: str, data: MemberCreate
) -> User:
    email = data.email.lower()
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        tenant_id=tenant_id,
        email=email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # Automatically attach member to tenant's first workspace if it exists
    first_ws = (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.tenant_id == tenant_id, Workspace.status == "active")
            .limit(1)
        )
    ).scalars().first()

    if first_ws:
        ws_role = "admin" if data.role == "tenant_admin" else "member"
        db.add(WorkspaceMember(workspace_id=first_ws, user_id=user.id, role=ws_role))

    await db.commit()
    await db.refresh(user)
    return user


async def update_tenant_member(
    db: AsyncSession, tenant_id: str, member_id: str, data: MemberUpdate
) -> User:
    user = (
        await db.execute(
            select(User).where(User.id == member_id, User.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = hash_password(data.password)

    await db.commit()
    await db.refresh(user)
    return user


async def delete_tenant_member(
    db: AsyncSession, tenant_id: str, member_id: str, current_user_id: str
) -> None:
    if member_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    user = (
        await db.execute(
            select(User).where(User.id == member_id, User.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    await db.delete(user)
    await db.commit()