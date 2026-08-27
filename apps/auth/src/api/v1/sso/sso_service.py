"""SSO / OIDC business logic: initiate flow and handle callback."""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core import oidc
from src.core.roles import Roles
from src.core.security import (
    create_token_pair,
    hash_refresh_token,
    decode_token,
)
from src.models import RefreshToken, Tenant, User
from src.models.workspace import Workspace


def _slugify(value: str) -> str:
    import re

    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


async def initiate(
    session: httpx.AsyncClient,
) -> tuple[str, str, str]:
    """Return (authorization_url, csrf_state, code_verifier)."""
    settings = get_settings()
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
    """Exchange code, verify id_token, provision user, issue our JWTs."""
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

    user = (
        await db.execute(
            select(User).where(User.oidc_sub == sub)
        )
    ).scalars().first()

    if user is None:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()

    if user is None:
        tenant = Tenant(name="SSO Tenant", slug=_slugify(f"sso-{sub[:8]}"))
        db.add(tenant)
        await db.flush()

        user = User(
            tenant_id=tenant.id,
            email=email or f"{sub}@sso.local",
            hashed_password=None,
            full_name=id_claims.get("name", ""),
            role=Roles.TENANT_USER,
            auth_provider="sso",
            oidc_sub=sub,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        workspace = Workspace(
            tenant_id=tenant.id, name="SSO Workspace", slug=_slugify(f"sso-ws-{sub[:8]}")
        )
        db.add(workspace)
        await db.flush()
    else:
        if user.oidc_sub != sub:
            user.oidc_sub = sub
            user.auth_provider = "sso"

    # Pick the user's first workspace for the token ``wid``.
    first_ws = (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.tenant_id == user.tenant_id)
            .limit(1)
        )
    ).scalars().first()

    pair = create_token_pair(
        sub=user.id, tid=user.tenant_id, wid=first_ws, role=Roles.TENANT_USER
    )
    claims = decode_token(pair["refresh_token"], expected_type="refresh")
    from datetime import datetime, timezone

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(pair["refresh_token"]),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
    )
    await db.commit()
    await db.refresh(user)
    return user, pair