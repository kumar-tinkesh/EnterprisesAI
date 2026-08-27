"""SSO / OIDC API endpoints."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.config import get_settings
from src.api.v1.sso import schemas as sc
from src.api.v1.sso import sso_service

router = APIRouter(prefix="/sso", tags=["sso"])
settings = get_settings()


@router.get("/initiate", response_model=sc.SsoInitiateResponse)
async def sso_initiate(
    session: httpx.AsyncClient = Depends(lambda: httpx.AsyncClient(timeout=20)),
):
    url, state, _ = await sso_service.initiate(session)
    await session.aclose()
    return sc.SsoInitiateResponse(authorization_url=url, state=state)


@router.get("/callback", response_model=sc.SsoCallbackResponse)
async def sso_callback(
    code: str = Query(...),
    state: str = Query(""),
    code_verifier: str = Query(...),
    db: AsyncSession = Depends(get_db),
    session: httpx.AsyncClient = Depends(lambda: httpx.AsyncClient(timeout=20)),
):
    try:
        user, pair = await sso_service.handle_callback(
            db, code=code, code_verifier=code_verifier, session=session
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