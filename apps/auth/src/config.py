"""Global application settings.

This is the SINGLE source of truth for configuration in this project.
Every module imports ``get_settings()`` (cached singleton) so that any
value set in ``.env`` propagates globally across the whole service.

Environment variables take priority over values in the ``.env`` file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directory that contains this file (apps/auth).
BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Global settings loaded from the environment / ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    APP_NAME: str = "EnterpriseAI Auth Service"
    ENV: str = "development"
    DEBUG: bool = False
    SHOW_LOADED_ENV: bool = False

    # --- HTTP / CORS ------------------------------------------------------
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8001"]
    )

    # --- Database ---------------------------------------------------------
    DATABASE_URL: str = "sqlite+aiosqlite:///./auth.db"
    DB_ECHO: bool = False

    # --- JWT / RS256 ------------------------------------------------------
    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""
    JWT_ALGORITHM: str = "RS256"
    JWT_ISSUER: str = "enterprise-ai-auth"
    JWT_AUDIENCE: str = "enterprise-ai"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- SSO / OIDC -------------------------------------------------------
    SSO_PROVIDER: str = "google"
    SSO_CLIENT_ID: str = ""
    SSO_CLIENT_SECRET: str = ""
    SSO_DISCOVERY_URL: str = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )
    SSO_REDIRECT_URI: str = "http://localhost:8001/api/v1/sso/callback"

    # --- Security / CSRF --------------------------------------------------
    CSRF_SECRET_KEY: str = "change-me-in-production"
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_COOKIE_AGE: int = 60 * 60 * 3  # 3 hours

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _decode_cors(cls, v: Any) -> Any:
        """Allow either a JSON array string or an actual list from the env."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def key_dir(self) -> Path:
        return BASE_DIR / ".keys"

    def redacted_repr(self) -> dict[str, Any]:
        return {
            "APP_NAME": self.APP_NAME,
            "ENV": self.ENV,
            "DEBUG": self.DEBUG,
            "DATABASE_URL": self.DATABASE_URL,
            "API_V1_PREFIX": self.API_V1_PREFIX,
            "JWT_ALGORITHM": self.JWT_ALGORITHM,
            "JWT_ISSUER": self.JWT_ISSUER,
            "JWT_AUDIENCE": self.JWT_AUDIENCE,
            "SSO_PROVIDER": self.SSO_PROVIDER,
            "SSO_REDIRECT_URI": self.SSO_REDIRECT_URI,
        }


@lru_cache
def get_settings() -> Settings:
    """Return the singleton (cached) global settings object."""
    return Settings()