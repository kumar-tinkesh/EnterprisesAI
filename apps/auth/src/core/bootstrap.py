"""Create the first platform admin and the first tenant from the environment, once.

    ADMIN_EMAIL / ADMIN_PASSWORD (/ ADMIN_FULL_NAME)                      the vendor admin
    TENANT_NAME / TENANT_ADMIN_EMAIL / TENANT_ADMIN_PASSWORD (/ ..._FULL_NAME)  a company + its admin

Runs on every auth-service start, after migrations. If a vendor admin with
that email already exists nothing changes — not even its password, so a
password changed later in the app is never reset by a restart. Two instances
starting together can't create it twice: the unique email constraint decides,
and the loser just reports "exists".
"""
from __future__ import annotations

import logging

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.core.audit import log_audit_event
from src.core.roles import Roles
from src.core.security import hash_password
from src.models.tenant import VendorUser
from src.models.user import User

logger = logging.getLogger("auth.bootstrap")

MIN_PASSWORD = 8


def _usable(email: str, password: str, what: str) -> str | None:
    """The normalized email if this account can be created (and logged into), else None."""
    if len(password) < MIN_PASSWORD:
        logger.warning("%s password is shorter than %d characters; it was not created.", what, MIN_PASSWORD)
        return None
    try:
        # The same check login applies: an account that can't log in is no use.
        return validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        logger.warning("%s email %r can't be used to log in (%s); it was not created.", what, email, exc)
        return None


async def ensure_admin(db: AsyncSession, settings: Settings) -> str:
    """-> "created" | "exists" | "skipped" (not configured, or the password is too short)."""
    email = settings.ADMIN_EMAIL.strip().lower()
    password = settings.ADMIN_PASSWORD
    if not email or not password:
        return "skipped"
    email = _usable(email, password, "ADMIN")
    if email is None:
        return "skipped"
    if (await db.execute(select(VendorUser.id).where(VendorUser.email == email))).first():
        return "exists"
    admin = VendorUser(
        email=email,
        hashed_password=hash_password(password),
        full_name=settings.ADMIN_FULL_NAME.strip() or "Platform Admin",
        role=Roles.VENDOR_ADMIN,
        is_active=True,
    )
    db.add(admin)
    try:
        await db.flush()
        await log_audit_event(db, action="bootstrap_admin", user_id=admin.id, tenant_id=None, resource="vendor_user")
        await db.commit()
    except IntegrityError:  # another instance created it a moment ago
        await db.rollback()
        return "exists"
    return "created"


async def ensure_tenant(db: AsyncSession, settings: Settings) -> str:
    """-> "created" | "exists" | "skipped". The tenant comes with its admin and a
    first workspace, exactly as when a vendor admin creates one."""
    from src.api.v1.vendor.schemas import VendorTenantCreate
    from src.api.v1.vendor.service import create_vendor_tenant

    name = settings.TENANT_NAME.strip()
    email, password = settings.TENANT_ADMIN_EMAIL.strip().lower(), settings.TENANT_ADMIN_PASSWORD
    if not name or not email or not password:
        return "skipped"
    email = _usable(email, password, "TENANT_ADMIN")
    if email is None:
        return "skipped"
    if (await db.execute(select(User.id).where(User.email == email))).first():
        return "exists"
    try:
        await create_vendor_tenant(db, VendorTenantCreate(
            name=name, admin_email=email, admin_password=password,
            admin_full_name=settings.TENANT_ADMIN_FULL_NAME.strip() or "Tenant Admin",
        ))
    except IntegrityError:  # another instance made it a moment ago
        await db.rollback()
        return "exists"
    return "created"


__all__ = ["ensure_admin", "ensure_tenant"]
