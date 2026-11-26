"""Workspaces: list, create, rename/archive, members, switch.

    GET    /workspaces                          the ones I can see (+ what the UI may offer)
    POST   /workspaces                          tenant admin: a new workspace (creator becomes its admin)
    PATCH  /workspaces/{id}                     rename / describe; tenant admin: archive or restore
    GET    /workspaces/{id}/members             who is in it
    POST   /workspaces/{id}/members             add someone from the tenant (or change their role)
    PATCH  /workspaces/{id}/members/{user_id}   change a member's role
    DELETE /workspaces/{id}/members/{user_id}   take someone out
    POST   /workspaces/{id}/switch              new tokens for that workspace

Solo accounts get 403 on everything that would create or switch.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.api.v1.auth.schemas import AccountOut
from src.api.v1.workspaces import schemas as sc
from src.api.v1.workspaces import service as svc
from src.core.audit import log_audit_event
from src.core.roles import Roles
from src.db.session import get_db

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _tenant_account(current: CurrentUser) -> CurrentUser:
    if current.role == Roles.VENDOR_ADMIN or not current.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspaces are for workspace accounts.")
    return current


async def _row(db: AsyncSession, current: CurrentUser, workspace_id: str) -> sc.WorkspaceOut:
    rows = await svc.list_workspaces(db, user=current, current_id=current.workspace_id, include_archived=True)
    return sc.WorkspaceOut(**next(r for r in rows if r["id"] == workspace_id))


@router.get("", response_model=sc.WorkspaceList)
async def list_workspaces(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    rows = await svc.list_workspaces(
        db, user=current, current_id=current.workspace_id,
        include_archived=include_archived and current.role == Roles.TENANT_ADMIN,
    )
    team = current.role in (Roles.TENANT_ADMIN, Roles.TENANT_USER)
    return sc.WorkspaceList(
        workspaces=rows,
        current_id=current.workspace_id,
        can_create=current.role == Roles.TENANT_ADMIN,
        can_switch=team and sum(1 for r in rows if r["status"] == "active") > 1,
    )


@router.post("", response_model=sc.WorkspaceOut, status_code=201)
async def create_workspace(
    payload: sc.WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    ws = await svc.create_workspace(db, user=current, name=payload.name, description=payload.description)
    await log_audit_event(db, action="workspace_create", user_id=current.id, tenant_id=current.tenant_id, resource="workspace")
    await db.commit()
    return await _row(db, current, ws.id)


@router.patch("/{workspace_id}", response_model=sc.WorkspaceOut)
async def update_workspace(
    workspace_id: str,
    payload: sc.WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    ws = await svc.update_workspace(
        db, user=current, workspace_id=workspace_id, name=payload.name,
        description=payload.description, status_=payload.status,
    )
    return await _row(db, current, ws.id)


@router.get("/{workspace_id}/members", response_model=list[sc.WorkspaceMemberOut])
async def list_members(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    return await svc.list_members(db, user=current, workspace_id=workspace_id)


@router.post("/{workspace_id}/members", response_model=list[sc.WorkspaceMemberOut], status_code=201)
async def add_member(
    workspace_id: str,
    payload: sc.MemberAdd,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    await svc.add_member(db, user=current, workspace_id=workspace_id, member_id=payload.user_id, role=payload.role)
    return await svc.list_members(db, user=current, workspace_id=workspace_id)


@router.patch("/{workspace_id}/members/{user_id}", response_model=list[sc.WorkspaceMemberOut])
async def update_member(
    workspace_id: str,
    user_id: str,
    payload: sc.MemberRole,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    await svc.update_member(db, user=current, workspace_id=workspace_id, member_id=user_id, role=payload.role)
    return await svc.list_members(db, user=current, workspace_id=workspace_id)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _tenant_account(current)
    await svc.remove_member(db, user=current, workspace_id=workspace_id, member_id=user_id)


@router.post("/{workspace_id}/switch", response_model=sc.SwitchResponse)
async def switch_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    from src.api.v1.auth.service import _issue_pair

    _tenant_account(current)
    if current.role == Roles.SOLO_USER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A personal account has one workspace.")
    if not await svc.can_enter(
        db, user_id=current.id, role=current.role, tenant_id=current.tenant_id, workspace_id=workspace_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    tokens = await _issue_pair(db, current.id, current.role, current.tenant_id, workspace_id)
    await log_audit_event(db, action="workspace_switch", user_id=current.id, tenant_id=current.tenant_id, resource="workspace")
    await db.commit()
    return sc.SwitchResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user=AccountOut(
            id=current.id, email=current.email, full_name=current.full_name, role=current.role,
            tenant_id=current.tenant_id, workspace_id=workspace_id,
        ),
    )
