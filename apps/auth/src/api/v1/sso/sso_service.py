"""SSO / OIDC business logic: initiate flow and handle callback."""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import oidc
from src.core.roles import Roles
from src.core.security import (
    create_token_pair,
    hash_refresh_token,
    decode_token,
)
from src.core.audit import log_audit_event
from src.models import RefreshToken, SsoConfig, Tenant, User
from src.models.workspace import Workspace


async def get_sso_config(db: AsyncSession, tenant_id: str) -> SsoConfig | None:
    """Retrieve the SSO configuration for a tenant."""
    res = await db.execute(
        select(SsoConfig).where(SsoConfig.tenant_id == tenant_id, SsoConfig.enabled.is_(True))
    )
    return res.scalars().first()


async def save_sso_config(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str = "google",
    client_id: str,
    client_secret: str,
    discovery_url: str,
    redirect_uri: str = "",
    enabled: bool = True,
) -> SsoConfig:
    """Create or update a tenant's SSO configuration."""
    existing = await get_sso_config(db, tenant_id)
    if existing:
        existing.provider = provider
        existing.client_id = client_id
        existing.client_secret = client_secret
        existing.discovery_url = discovery_url
        existing.redirect_uri = redirect_uri
        existing.enabled = enabled
        config = existing
    else:
        config = SsoConfig(
            tenant_id=tenant_id,
            provider=provider,
            client_id=client_id,
            client_secret=client_secret,
            discovery_url=discovery_url,
            redirect_uri=redirect_uri,
            enabled=enabled,
        )
        db.add(config)

    await log_audit_event(
        db,
        action="update_sso_config",
        tenant_id=tenant_id,
        resource="sso_config",
        detail=f"Provider: {provider}",
    )
    await db.commit()
    await db.refresh(config)
    return config


def _slugify(value: str) -> str:
    import re

    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


async def initiate(
    session: httpx.AsyncClient,
    db: AsyncSession | None = None,
    tenant_id: str | None = None,
) -> tuple[str, str, str]:
    """Return (authorization_url, csrf_state, code_verifier). Supports dynamic per-tenant OIDC."""
    discovery_url = None
    if db and tenant_id:
        cfg = await get_sso_config(db, tenant_id)
        if cfg and cfg.discovery_url:
            discovery_url = cfg.discovery_url

    state = oidc.generate_state()
    verifier, challenge = oidc.pkce_pair()
    discovery = await oidc.get_discovery(session, discovery_url=discovery_url)
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
    tenant_id: str | None = None,
) -> tuple[User, dict[str, str]]:
    """Exchange code, verify id_token, provision user, issue our JWTs."""
    discovery_url = None
    if tenant_id:
        cfg = await get_sso_config(db, tenant_id)
        if cfg and cfg.discovery_url:
            discovery_url = cfg.discovery_url

    discovery = await oidc.get_discovery(session, discovery_url=discovery_url)
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
    await log_audit_event(
        db, action="sso_login", user_id=user.id, tenant_id=user.tenant_id, resource="sso"
    )
    await db.commit()
    await db.refresh(user)
    return user, pair