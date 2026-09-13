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

    # Native per-user device-pairing bridges (see
    # vendor.services.whatsapp_bridge) — each user's bridge process gets an
    # isolated cwd under this root and a port in this range.
    WHATSAPP_BRIDGE_BINARY: str = "/app/bin/whatsapp-bridge"
    # The vendored+patched MCP server (see vendor_src/README.md) that talks
    # to a bridge instance over HTTP — run with the app's own interpreter
    # (its httpx/mcp/requests deps are already installed there).
    WHATSAPP_MCP_SERVER_SCRIPT: str = (
        "/app/apps/backend/vendor/services/whatsapp_bridge/vendor_src/server/main.py"
    )
    WHATSAPP_BRIDGE_DATA_ROOT: str = "/data/whatsapp_bridges"
    WHATSAPP_BRIDGE_PORT_RANGE_START: int = 20000
    WHATSAPP_BRIDGE_PORT_RANGE_END: int = 21000
    # Kill a bridge that's had no successful "connected" heartbeat for this
    # long — bounds total resource usage (each is a real OS process).
    WHATSAPP_BRIDGE_IDLE_TIMEOUT_SECONDS: int = 6 * 60 * 60


@lru_cache
def get_backend_settings() -> BackendSettings:
    """Return the cached backend settings singleton."""
    return BackendSettings()
