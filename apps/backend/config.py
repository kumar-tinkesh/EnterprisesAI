"""Backend service configuration.

The backend reuses the Auth service's database engine and JWT verification
(``src.db.session``, ``src.api.deps``) — there is no second engine and no
duplicated JWT config. This module only adds backend-specific settings such as
the vendor vault key and the API prefix.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import get_settings as get_auth_settings


class BackendSettings(BaseSettings):
    """Backend-specific settings (composed on top of the auth settings)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Vendor resources ------------------------------------------------
    # 32-byte urlsafe-base64 key for AES-256-GCM tool-secret encryption.
    # If empty, a deterministic dev-only key is derived (NEVER in production).
    VENDOR_VAULT_KEY: str = ""

    # --- HTTP ------------------------------------------------------------
    BACKEND_API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8001",
            "http://localhost:8002",
        ]
    )


@lru_cache
def get_backend_settings() -> BackendSettings:
    """Return the cached backend settings singleton."""
    return BackendSettings()


def get_database_url() -> str:
    """Return the shared DATABASE_URL from the auth settings."""
    return get_auth_settings().DATABASE_URL