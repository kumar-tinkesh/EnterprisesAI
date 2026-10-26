"""SSO / OIDC business logic: initiate flow and handle Google callback for solo users."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import oidc
from src.core.roles import Roles
from src.core.security import (
    create_token_pair,
    decode_token,
    hash_refresh_token,
)
from src.core.audit import log_audit_event
from src.models import RefreshToken, Tenant, User
from src.models.workspace import Workspace, WorkspaceMember


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


async def _unique_tenant_slug(db: AsyncSession, base: str) -> str:
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


async def initiate(
    session: httpx.AsyncClient,
) -> tuple[str, str, str]:
    """Return (authorization_url, csrf_state, code_verifier) for platform Google OAuth."""
    state = oidc.generate_state()
    verifier, challenge = oidc.pkce_pair()
    discovery = await oidc.get_discovery(session)
    url = await oidc.build_authorization_url(
        session,
        state=state,
        code_challenge=challenge,
        discovery=discovery,
    )
    return url, state, verifier


async def handle_callback(
    db: AsyncSession,
    *,
    code: str,
    code_verifier: str,
    session: httpx.AsyncClient,
) -> tuple[User, dict[str, str]]:
    """Exchange code, verify id_token, provision solo_user if new, issue JWT pair."""
    discovery = await oidc.get_discovery(session)
    tokens = await oidc.exchange_code(
        session,
        code=code,
        code_verifier=code_verifier,
        discovery=discovery,
    )
    id_claims = await oidc.verify_id_token(
        tokens["id_token"], session=session, discovery=discovery
    )

    email = (id_claims.get("email") or "").lower()
    sub = str(id_claims["sub"])
    full_name = id_claims.get("name") or "Google User"

    user = (
        await db.execute(
            select(User).where(User.oidc_sub == sub)
        )
    ).scalars().first()

    if user is None and email:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()

    if user is None:
        # Provision a new solo_user with personal tenant + workspace
        personal_name = f"{full_name}'s Workspace"
        personal_slug = await _unique_tenant_slug(db, _slugify(full_name or "solo"))
        tenant = Tenant(name=personal_name, slug=personal_slug, is_personal=True)
        db.add(tenant)
        await db.flush()

        user = User(
            tenant_id=tenant.id,
            email=email or f"{sub}@sso.local",
            hashed_password=None,
            full_name=full_name,
            role=Roles.SOLO_USER,
            auth_provider="sso",
            oidc_sub=sub,
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
    else:
        if user.oidc_sub != sub:
            user.oidc_sub = sub
            user.auth_provider = "sso"
        if user.role == Roles.TENANT_USER:
            user.role = Roles.SOLO_USER

    first_ws = (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.tenant_id == user.tenant_id)
            .limit(1)
        )
    ).scalars().first()

    pair = create_token_pair(
        sub=user.id, tid=user.tenant_id, wid=first_ws, role=user.role
    )
    claims = decode_token(pair["refresh_token"], expected_type="refresh")

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(pair["refresh_token"]),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
    )
    await log_audit_event(
        db, action="sso_login", user_id=user.id, tenant_id=user.tenant_id, resource="sso"
    )
    await db.commit()
    await db.refresh(user)
    return user, pair