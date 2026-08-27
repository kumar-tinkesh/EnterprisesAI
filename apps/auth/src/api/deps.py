"""Reusable API dependencies: bearer-token auth + role guards."""
from __future__ import annotations

from typing import Callable

import jwt as pyjwt

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models import User, VendorUser
from src.core.roles import Roles
from src.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """Authenticated account identity read from the access token + DB."""

    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str | None = None
    is_active: bool = True

    @property
    def is_vendor(self) -> bool:
        return self.role == Roles.VENDOR_ADMIN

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == Roles.TENANT_ADMIN


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Resolve the authenticated account (user or vendor) from the token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(credentials.credentials, expected_type="access")
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    role = claims.get("role", "")
    sub = claims["sub"]

    if role == Roles.VENDOR_ADMIN:
        row = (
            await db.execute(select(VendorUser).where(VendorUser.id == sub))
        ).scalars().first()
        if row is None or not row.is_active:
            raise HTTPException(
                status_code=401, detail="Account not found or deactivated"
            )
        return CurrentUser(
            id=row.id,
            email=row.email,
            full_name=row.full_name,
            role=row.role,
            tenant_id=None,
            is_active=row.is_active,
        )

    row = (
        await db.execute(select(User).where(User.id == sub, User.is_active.is_(True)))
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=401, detail="Account not found or deactivated")
    return CurrentUser(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        role=row.role,
        tenant_id=row.tenant_id,
        is_active=row.is_active,
    )


def require_roles(*allowed_roles: str) -> Callable:
    """Build a FastAPI dependency that returns the current user only if their
    role is in ``allowed_roles``; otherwise raises 403 Forbidden."""

    async def _guard(
        current: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return current

    return _guard
