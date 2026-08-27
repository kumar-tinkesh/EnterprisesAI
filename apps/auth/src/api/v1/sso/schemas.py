"""SSO / OIDC endpoint schemas."""
from __future__ import annotations

from pydantic import BaseModel


class SsoInitiateResponse(BaseModel):
    authorization_url: str
    state: str


class SsoCallbackRequest(BaseModel):
    code: str
    state: str = ""


class SsoCallbackResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str