"""Backend service configuration.

The backend reuses the Auth service's database engine and JWT verification
(``src.db.session``, ``src.api.deps``) — there is no second engine and no
duplicated JWT config. This module only adds backend-specific settings
such as the API prefix.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict



class BackendSettings(BaseSettings):
    """Backend-specific settings (composed on top of the auth settings)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    BACKEND_API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8001",
            "http://localhost:8002",
        ]
    )
    # Browser-reachable base URL for this service — used to build the one
    # shared OAuth redirect_uri (see vendor.services.oauth_flow)
    # that every vendor-OAuth MCP server registers in its own provider
    # console. Override for a real deployment (must be HTTPS in production
    # per most providers' rules); localhost is fine for sandbox testing.
    BACKEND_PUBLIC_URL: str = "http://localhost:8002"

    # Per-user device-pairing bridges (see vendor.services.whatsapp_bridge):
    # each user's bridge runs in its own container, started/stopped only by
    # the whatsapp-orchestrator service (the one holding docker.sock).
    WHATSAPP_ORCHESTRATOR_URL: str = "http://whatsapp-orchestrator:8090"
    WHATSAPP_ORCHESTRATOR_API_KEY: str = ""
    # The vendored+patched MCP server (see vendor_src/README.md) that talks
    # to a user's bridge container over HTTP — run with the app's own
    # interpreter (its httpx/mcp/requests deps are already installed there).
    WHATSAPP_MCP_SERVER_SCRIPT: str = (
        "/app/apps/backend/vendor/services/whatsapp_bridge/vendor_src/server/main.py"
    )
    # Added to a bare 10-digit number someone sends to ("8789977380" -> "918789977380"); WhatsApp needs
    # the country code. Empty = such a number is refused with a clear error instead.
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = "91"


@lru_cache
def get_backend_settings() -> BackendSettings:
    """Return the cached backend settings singleton."""
    return BackendSettings()
