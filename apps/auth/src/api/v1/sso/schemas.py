"""SSO / OIDC endpoint schemas."""
from __future__ import annotations

from pydantic import BaseModel


class SsoInitiateResponse(BaseModel):
    authorization_url: str
    state: str
    code_verifier: str | None = None


class SsoCallbackResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str


class SsoConfigCreate(BaseModel):
    provider: str = "google"
    client_id: str
    client_secret: str
    discovery_url: str
    redirect_uri: str = ""
    enabled: bool = True


class SsoConfigResponse(BaseModel):
    id: str
    tenant_id: str
    provider: str
    client_id: str
    discovery_url: str
    redirect_uri: str
    enabled: bool