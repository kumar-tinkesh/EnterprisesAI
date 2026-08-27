"""Role-scoped dashboard endpoints.

Four dashboards matching the four roles:

* ``vendor_admin``  ->  /api/v1/dashboard/vendor
* ``tenant_admin``  ->  /api/v1/dashboard/tenant
* ``tenant_user``   ->  /api/v1/dashboard/user
* ``solo_user``     ->  /api/v1/dashboard/workspace
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.api.v1.dashboard.schemas import DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/vendor", response_model=DashboardResponse)
async def dashboard_vendor(
    current: CurrentUser = Depends(require_roles(Roles.VENDOR_ADMIN)),
):
    return DashboardResponse(
        dashboard="vendor",
        role=current.role,
        message=f"Vendor admin dashboard for {current.email}",
    )


@router.get("/tenant", response_model=DashboardResponse)
async def dashboard_tenant(
    current: CurrentUser = Depends(require_roles(Roles.TENANT_ADMIN)),
):
    return DashboardResponse(
        dashboard="tenant",
        role=current.role,
        message=f"Tenant admin dashboard for {current.email}",
    )


@router.get("/user", response_model=DashboardResponse)
async def dashboard_user(
    current: CurrentUser = Depends(require_roles(Roles.TENANT_USER, Roles.SOLO_USER)),
):
    return DashboardResponse(
        dashboard="user",
        role=current.role,
        message=f"User dashboard for {current.email}",
    )


@router.get("/workspace", response_model=DashboardResponse)
async def dashboard_workspace(
    current: CurrentUser = Depends(require_roles(Roles.SOLO_USER, Roles.TENANT_USER, Roles.TENANT_ADMIN)),
):
    return DashboardResponse(
        dashboard="workspace",
        role=current.role,
        message=f"Workspace dashboard for {current.email}",
    )