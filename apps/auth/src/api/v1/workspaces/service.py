"""Workspaces inside a tenant: who can see which, create, members, switching.

Rules
-----
* A solo user has exactly one workspace (made at signup). They can't make more,
  and the UI shows no switcher.
* A tenant admin sees and manages every workspace in their tenant.
* A tenant user sees only the workspaces they are a member of.
* The access token carries the current workspace (``wid``). Every request checks
  it again (see :func:`resolve_workspace`); a stale or foreign ``wid`` falls back
  to the person's first workspace instead of failing.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.roles import Roles
from src.models import User
from src.models.workspace import Workspace, WorkspaceMember

WS_ADMIN = "admin"
WS_MEMBER = "member"
WS_ROLES = (WS_ADMIN, WS_MEMBER)


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "workspace"


async def _unique_slug(db: AsyncSession, tenant_id: str, name: str) -> str:
    base = _slugify(name)
    candidate, n = base, 2
    while (
        await db.execute(select(Workspace.id).where(Workspace.tenant_id == tenant_id, Workspace.slug == candidate))
    ).scalars().first():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


# ── which workspace is this request in ────────────────────────────────────────


async def _membership(db: AsyncSession, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return (
        await db.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        )
    ).scalars().first()


async def can_enter(db: AsyncSession, *, user_id: str, role: str, tenant_id: str | None, workspace_id: str) -> bool:
    """May this person work in this workspace right now?"""
    if not tenant_id:
        return False
    ws = (
        await db.execute(
            select(Workspace).where(
                Workspace.id == workspace_id, Workspace.tenant_id == tenant_id, Workspace.status == "active"
            )
        )
    ).scalars().first()
    if ws is None:
        return False
    if role == Roles.TENANT_ADMIN:
        return True
    return await _membership(db, workspace_id, user_id) is not None


async def default_workspace_id(db: AsyncSession, *, user_id: str, role: str, tenant_id: str | None) -> str | None:
    """The person's first active workspace (by membership; a tenant admin falls
    back to any workspace of the tenant)."""
    if not tenant_id:
        return None
    first = (
        await db.execute(
            select(Workspace.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id, Workspace.tenant_id == tenant_id, Workspace.status == "active")
            .order_by(Workspace.created_at, Workspace.id)
            .limit(1)
        )
    ).scalars().first()
    if first or role != Roles.TENANT_ADMIN:
        return first
    return (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.tenant_id == tenant_id, Workspace.status == "active")
            .order_by(Workspace.created_at, Workspace.id)
            .limit(1)
        )
    ).scalars().first()


async def resolve_workspace(
    db: AsyncSession, *, user_id: str, role: str, tenant_id: str | None, requested: str | None
) -> str | None:
    """The token's workspace if it's still allowed, else the person's default."""
    if requested and await can_enter(db, user_id=user_id, role=role, tenant_id=tenant_id, workspace_id=requested):
        return requested
    return await default_workspace_id(db, user_id=user_id, role=role, tenant_id=tenant_id)


# ── listing ───────────────────────────────────────────────────────────────────


async def _member_counts(db: AsyncSession, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
        .where(WorkspaceMember.workspace_id.in_(ids))
        .group_by(WorkspaceMember.workspace_id)
    )
    return dict(rows.tuples().all())


async def list_workspaces(db: AsyncSession, *, user: User, current_id: str | None, include_archived: bool) -> list[dict]:
    if user.role == Roles.TENANT_ADMIN:
        query = select(Workspace).where(Workspace.tenant_id == user.tenant_id)
    else:
        query = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id, Workspace.tenant_id == user.tenant_id)
        )
    if not include_archived:
        query = query.where(Workspace.status == "active")
    workspaces = list((await db.execute(query.order_by(Workspace.created_at, Workspace.id))).scalars())
    ids = [w.id for w in workspaces]
    mine = dict(
        (
            await db.execute(
                select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
                    WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id.in_(ids or [""])
                )
            )
        ).tuples().all()
    )
    counts = await _member_counts(db, ids)
    return [
        {
            "id": w.id,
            "name": w.name,
            "slug": w.slug,
            "description": w.description or "",
            "status": w.status,
            # A tenant admin manages every workspace, member or not.
            "my_role": WS_ADMIN if user.role == Roles.TENANT_ADMIN else mine.get(w.id, WS_MEMBER),
            "is_member": w.id in mine,
            "member_count": counts.get(w.id, 0),
            "is_current": w.id == current_id,
            "created_at": w.created_at,
        }
        for w in workspaces
    ]


# ── managing ──────────────────────────────────────────────────────────────────


def _require_tenant_account(user: User) -> None:
    if user.role == Roles.SOLO_USER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "A personal account has one workspace. Workspaces are part of team (tenant) accounts.",
        )
    if user.role not in (Roles.TENANT_ADMIN, Roles.TENANT_USER) or not user.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspaces are for tenant accounts.")


async def get_manageable(db: AsyncSession, *, user: User, workspace_id: str) -> Workspace:
    """A workspace of the caller's tenant that the caller may change (tenant
    admin, or an admin of that workspace)."""
    _require_tenant_account(user)
    ws = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == user.tenant_id))
    ).scalars().first()
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    if user.role == Roles.TENANT_ADMIN:
        return ws
    m = await _membership(db, ws.id, user.id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    if m.role != WS_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only this workspace's admins can change it.")
    return ws


async def create_workspace(db: AsyncSession, *, user: User, name: str, description: str) -> Workspace:
    _require_tenant_account(user)
    if user.role != Roles.TENANT_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a tenant admin can create workspaces.")
    name = name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the workspace a name.")
    taken = (
        await db.execute(
            select(Workspace.id).where(
                Workspace.tenant_id == user.tenant_id, func.lower(Workspace.name) == name.lower(), Workspace.status == "active"
            )
        )
    ).scalars().first()
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace with that name already exists.")
    ws = Workspace(
        tenant_id=user.tenant_id,
        name=name,
        slug=await _unique_slug(db, user.tenant_id, name),
        description=description.strip() or None,
    )
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WS_ADMIN))
    await db.commit()
    await db.refresh(ws)
    return ws


async def _active_count(db: AsyncSession, tenant_id: str) -> int:
    return (
        await db.execute(
            select(func.count(Workspace.id)).where(Workspace.tenant_id == tenant_id, Workspace.status == "active")
        )
    ).scalar_one()


async def update_workspace(
    db: AsyncSession, *, user: User, workspace_id: str, name: str | None, description: str | None, status_: str | None
) -> Workspace:
    ws = await get_manageable(db, user=user, workspace_id=workspace_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the workspace a name.")
        clash = (
            await db.execute(
                select(Workspace.id).where(
                    Workspace.tenant_id == ws.tenant_id,
                    func.lower(Workspace.name) == name.lower(),
                    Workspace.id != ws.id,
                    Workspace.status == "active",
                )
            )
        ).scalars().first()
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "A workspace with that name already exists.")
        ws.name = name
    if description is not None:
        ws.description = description.strip() or None
    if status_ is not None and status_ != ws.status:
        if user.role != Roles.TENANT_ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a tenant admin can archive or restore a workspace.")
        if status_ == "archived" and await _active_count(db, ws.tenant_id) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This is the last active workspace; it can't be archived.")
        ws.status = status_
    await db.commit()
    await db.refresh(ws)
    return ws


async def list_members(db: AsyncSession, *, user: User, workspace_id: str) -> list[dict]:
    _require_tenant_account(user)
    ws = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == user.tenant_id))
    ).scalars().first()
    if ws is None or (
        user.role != Roles.TENANT_ADMIN and await _membership(db, workspace_id, user.id) is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    rows = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at)
    )
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "tenant_role": u.role,
            "role": m.role,
            "is_active": u.is_active,
            "added_at": m.created_at,
        }
        for m, u in rows.tuples().all()
    ]


async def _admin_count(db: AsyncSession, workspace_id: str) -> int:
    return (
        await db.execute(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == WS_ADMIN
            )
        )
    ).scalar_one()


async def add_member(db: AsyncSession, *, user: User, workspace_id: str, member_id: str, role: str) -> None:
    ws = await get_manageable(db, user=user, workspace_id=workspace_id)
    other = (
        await db.execute(select(User).where(User.id == member_id, User.tenant_id == ws.tenant_id))
    ).scalars().first()
    if other is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't in this tenant.")
    existing = await _membership(db, ws.id, other.id)
    if existing:
        existing.role = role
    else:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=other.id, role=role))
    await db.commit()


async def update_member(db: AsyncSession, *, user: User, workspace_id: str, member_id: str, role: str) -> None:
    ws = await get_manageable(db, user=user, workspace_id=workspace_id)
    m = await _membership(db, ws.id, member_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this workspace.")
    if m.role == WS_ADMIN and role != WS_ADMIN and await _admin_count(db, ws.id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A workspace needs at least one admin.")
    m.role = role
    await db.commit()


async def remove_member(db: AsyncSession, *, user: User, workspace_id: str, member_id: str) -> None:
    ws = await get_manageable(db, user=user, workspace_id=workspace_id)
    m = await _membership(db, ws.id, member_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this workspace.")
    if m.role == WS_ADMIN and await _admin_count(db, ws.id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A workspace needs at least one admin.")
    await db.delete(m)
    await db.commit()
