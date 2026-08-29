"""Unified auth business logic: signup / login / refresh / logout for the three
roles (vendor_admin -> VendorUser, tenant_admin/tenant_user -> User)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_audit_event
from src.core.roles import Roles
from src.core.security import (
    create_token_pair,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from src.models import RefreshToken, Tenant, User, VendorUser
from src.models.workspace import Workspace, WorkspaceMember


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


async def _unique_tenant_slug(db: AsyncSession, base: str) -> str:
    """Return a tenant slug that is guaranteed unique (suffix on collision)."""
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


async def _issue_pair(
    db: AsyncSession, account_id: str, role: str, tenant_id: str | None,
    workspace_id: str | None,
) -> dict[str, str]:
    """Create access+refresh tokens, persist the refresh hash, return tokens."""
    tokens = create_token_pair(sub=account_id, tid=tenant_id, wid=workspace_id, role=role)
    claims = decode_token(tokens["refresh_token"], expected_type="refresh")
    db.add(
        RefreshToken(
            user_id=account_id,
            token_hash=hash_refresh_token(tokens["refresh_token"]),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
    )
    await db.flush()
    return tokens


async def _first_workspace_id(db: AsyncSession, tenant_id: str) -> str | None:
    row = (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.tenant_id == tenant_id, Workspace.status == "active")
            .limit(1)
        )
    ).scalars().first()
    return row


async def signup(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    role: str,
    tenant_name: str,
) -> tuple[User | VendorUser, dict[str, str]]:
    """Create an account for any of the four roles and return tokens."""
    email = email.lower()

    if role == Roles.VENDOR_ADMIN:
        existing = (
            await db.execute(select(VendorUser).where(VendorUser.email == email))
        ).scalars().first()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        vendor = VendorUser(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=Roles.VENDOR_ADMIN,
            is_active=True,
        )
        db.add(vendor)
        await db.flush()
        tokens = await _issue_pair(db, vendor.id, Roles.VENDOR_ADMIN, None, None)
        await log_audit_event(db, action="signup", user_id=vendor.id, tenant_id=None, resource="vendor_user")
        await db.commit()
        await db.refresh(vendor)
        return vendor, tokens

    # ── Solo user: auto-create a hidden personal tenant + workspace ──
    if role == Roles.SOLO_USER:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

        personal_name = f"{full_name}'s Workspace" if full_name else "Personal Workspace"
        personal_slug = await _unique_tenant_slug(db, _slugify(full_name or "solo"))
        tenant = Tenant(name=personal_name, slug=personal_slug, is_personal=True)
        db.add(tenant)
        await db.flush()

        user = User(
            tenant_id=tenant.id,
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=Roles.SOLO_USER,
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name=personal_name,
            slug=_slugify(f"{personal_slug}-ws"),
        )
        db.add(workspace)
        await db.flush()

        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))

        tokens = await _issue_pair(db, user.id, Roles.SOLO_USER, tenant.id, workspace.id)
        await log_audit_event(db, action="signup", user_id=user.id, tenant_id=tenant.id, resource="user")
        await db.commit()
        await db.refresh(user)
        return user, tokens

    # ── tenant_user & tenant_admin self-signup is disabled ──
    if role == Roles.TENANT_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tenant user self-signup is disabled. Please contact your tenant admin for an invitation.",
        )
    if role == Roles.TENANT_ADMIN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tenant admin self-signup is disabled. Please contact the platform vendor admin to provision your organization.",
        )

    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"Invalid role '{role}'. Must be one of {Roles.ALL}",
    )



async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    role: str | None,
    workspace_id: str | None,
) -> tuple[User | VendorUser, dict[str, str]]:
    """Unified login. When ``role`` is given it disambiguates between the
    vendor table and the tenant table."""
    email = email.lower()

    if role == Roles.VENDOR_ADMIN:
        vendor = (
            await db.execute(
                select(VendorUser).where(
                    VendorUser.email == email, VendorUser.is_active.is_(True)
                )
            )
        ).scalars().first()
        if vendor is None or not vendor.hashed_password or not verify_password(
            password, vendor.hashed_password
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
        tokens = await _issue_pair(db, vendor.id, Roles.VENDOR_ADMIN, None, None)
        await db.commit()
        return vendor, tokens

    if role is None:
        # Auto-detect: tenant table first, then vendor table.
        user = (
            await db.execute(
                select(User).where(User.email == email, User.is_active.is_(True))
            )
        ).scalars().first()
        if user is not None:
            role = user.role
        else:
            vendor = (
                await db.execute(
                    select(VendorUser).where(
                        VendorUser.email == email, VendorUser.is_active.is_(True)
                    )
                )
            ).scalars().first()
            if vendor is not None:
                return await login(
                    db, email=email, password=password,
                    role=Roles.VENDOR_ADMIN, workspace_id=None,
                )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    else:
        user = (
            await db.execute(
                select(User).where(User.email == email, User.is_active.is_(True))
            )
        ).scalars().first()
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
        role = user.role

    if user.hashed_password is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if user.auth_provider != "local":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account signs in via SSO")

    wid = workspace_id or await _first_workspace_id(db, user.tenant_id)
    tokens = await _issue_pair(db, user.id, role, user.tenant_id, wid)
    await log_audit_event(db, action="login", user_id=user.id, tenant_id=user.tenant_id, resource="auth")
    await db.commit()
    return user, tokens


async def refresh_tokens(db: AsyncSession, *, refresh_token: str) -> dict[str, str]:
    try:
        claims = decode_token(refresh_token, expected_type="refresh")
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    stored = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(refresh_token),
                RefreshToken.revoked.is_(False),
            )
        )
    ).scalars().first()
    if stored is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token not found")

    sub = claims["sub"]
    role = claims.get("role", "")
    if role == Roles.VENDOR_ADMIN:
        account: User | VendorUser | None = (
            await db.execute(
                select(VendorUser).where(VendorUser.id == sub, VendorUser.is_active.is_(True))
            )
        ).scalars().first()
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
        tenant_id: str | None = None
        wid: str | None = None
    else:
        account = (
            await db.execute(
                select(User).where(User.id == sub, User.is_active.is_(True))
            )
        ).scalars().first()
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
        tenant_id = account.tenant_id
        wid = await _first_workspace_id(db, tenant_id)

    new = await _issue_pair(db, account.id, role, tenant_id, wid)
    stored.revoked = True
    stored.replaced_by = hash_refresh_token(new["refresh_token"])
    await log_audit_event(db, action="refresh_token", user_id=account.id, tenant_id=tenant_id, resource="auth")
    await db.commit()
    return new


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    stored = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(refresh_token),
                RefreshToken.revoked.is_(False),
            )
        )
    ).scalars().first()
    if stored:
        stored.revoked = True
        await log_audit_event(db, action="logout", user_id=stored.user_id, resource="auth")
        await db.commit()
