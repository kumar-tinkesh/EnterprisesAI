"""API v1 aggregator router."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.auth.router import router as auth_router
from src.api.v1.sso.router import router as sso_router
from src.api.v1.tenant.router import router as tenant_router
from src.api.v1.vendor.router import router as vendor_router
from src.api.v1.dashboard.router import router as dashboard_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(sso_router)
api_router.include_router(tenant_router)
api_router.include_router(vendor_router)
api_router.include_router(dashboard_router)