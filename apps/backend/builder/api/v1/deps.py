"""Shared dependencies and helpers for the builder API."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse

from src.api.deps import CurrentUser, get_current_user
from src.core.roles import Roles

from builder.graph.validation import GraphProblem


async def get_end_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Builder features are for workspace users (tenant admins/users, solo users)."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is for workspace users; this account has no tenant.",
        )
    return user


def can_manage(owner_id: str, user: CurrentUser) -> bool:
    """Change/delete a shared definition: its creator or a tenant admin."""
    return owner_id == user.id or user.role == Roles.TENANT_ADMIN


def problems_response(message: str, problems: list[GraphProblem], status_code: int = 422) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "problems": [p.as_dict() for p in problems]},
    )


def version_conflict(current: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": "Someone else saved a newer version. Reload to see it before saving again.", "version": current},
    )
