"""Tenant Resource Grants endpoints (Admin)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db

from vendor.api.v1.schemas import GrantResponse, GrantTenantResourceRequest
from vendor.services.mcp_service import grant_resource

logger = logging.getLogger("vendor.grants")

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


@router.post("/grants", response_model=GrantResponse)
async def post_grant_resource(
    payload: GrantTenantResourceRequest,
    response: Response,
    user: CurrentUser = _admin,
    db: AsyncSession = Depends(get_db),
):
    try:
        grant, created = await grant_resource(db, data=payload, actor_id=user.id)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(grant)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return grant
