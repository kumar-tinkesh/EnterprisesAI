"""SSO / OIDC API endpoints."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.config import get_settings
from src.api.deps import get_current_user
from src.api.v1.sso import schemas as sc
from src.api.v1.sso import sso_service

router = APIRouter(prefix="/sso", tags=["sso"])
settings = get_settings()


@router.get("/initiate", response_model=sc.SsoInitiateResponse)
async def sso_initiate(
    session: httpx.AsyncClient = Depends(lambda: httpx.AsyncClient(timeout=20)),
):
    url, state, verifier = await sso_service.initiate(session)
    await session.aclose()
    return sc.SsoInitiateResponse(authorization_url=url, state=state, code_verifier=verifier)


@router.get("/callback", response_model=sc.SsoCallbackResponse)
async def sso_callback(
    code: str = Query(...),
    state: str = Query(""),
    code_verifier: str = Query(...),
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    session: httpx.AsyncClient = Depends(lambda: httpx.AsyncClient(timeout=20)),
):
    try:
        user, pair = await sso_service.handle_callback(
            db, code=code, code_verifier=code_verifier, session=session, tenant_id=tenant_id
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="SSO callback failed") from exc
    finally:
        await session.aclose()
    return sc.SsoCallbackResponse(
        access_token=pair["access_token"],
        refresh_token=pair["refresh_token"],
        user_id=user.id,
    )


@router.get("/config", response_model=sc.SsoConfigResponse | None)
async def get_tenant_sso_config(
    db: AsyncSession = Depends(get_db),
    current=Depends(get_current_user),
):
    if not current.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with user")
    return await sso_service.get_sso_config(db, current.tenant_id)


@router.post("/config", response_model=sc.SsoConfigResponse)
async def update_tenant_sso_config(
    payload: sc.SsoConfigCreate,
    db: AsyncSession = Depends(get_db),
    current=Depends(get_current_user),
):
    if not current.tenant_id or current.role not in ("tenant_admin", "vendor_admin", "solo_user"):
        raise HTTPException(status_code=403, detail="Only tenant or vendor admins can update SSO config")
    return await sso_service.save_sso_config(
        db,
        tenant_id=current.tenant_id,
        provider=payload.provider,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        discovery_url=payload.discovery_url,
        redirect_uri=payload.redirect_uri,
        enabled=payload.enabled,
    )