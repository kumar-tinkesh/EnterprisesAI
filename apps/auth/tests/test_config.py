"""Tests for the global settings / .env loading."""
from __future__ import annotations

from src.config import Settings, get_settings


def test_settings_defaults():
    s = Settings()
    assert s.JWT_ALGORITHM == "RS256"
    assert s.API_V1_PREFIX == "/api/v1"
    assert s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert s.JWT_REFRESH_TOKEN_EXPIRE_MINUTES == 10080


def test_global_singleton():
    assert get_settings() is get_settings()


def test_cors_json_decode():
    s = Settings(BACKEND_CORS_ORIGINS='["http://a.com","http://b.com"]')
    assert s.BACKEND_CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_env_override():
    s = Settings(APP_NAME="Custom", JWT_AUDIENCE="custom-aud")
    assert s.APP_NAME == "Custom"
    assert s.JWT_AUDIENCE == "custom-aud"


def test_redacted_repr_has_no_secrets():
    s = Settings()
    red = s.redacted_repr()
    assert "JWT_PRIVATE_KEY" not in red
    assert "SSO_CLIENT_SECRET" not in red
    assert "CSRF_SECRET_KEY" not in red