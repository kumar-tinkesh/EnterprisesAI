"""Pytest fixtures and configuration for the auth service tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Configure global settings BEFORE importing any app module so the singleton
# engine picks up the test database.
_TMPDIR = Path(tempfile.mkdtemp(prefix="auth-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMPDIR / 'test.db'}"
os.environ["JWT_ISSUER"] = "testing-issuer"
os.environ["SSO_REDIRECT_URI"] = "http://testserver/api/v1/sso/callback"
os.environ["CSRF_SECRET_KEY"] = "test-secret-key"

from src.config import get_settings  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import SessionLocal, engine  # noqa: E402
from src.models import *  # noqa: E402,F403

settings = get_settings()


async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    await _reset_db()
    yield


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    from src.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac