"""Pytest fixtures for the Vendor Resources (backend) tests (MCP).

Uses an isolated async SQLite engine (separate from the auth service's shared
engine) so a combined ``pytest`` run never contaminates the auth tests. The
backend app's ``get_db`` dependency is overridden per-app to yield sessions
from the test engine; the shared ``src.db.session`` module is left untouched.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _mock_mcp_network(monkeypatch):
    """Stub MCP network probing so tests never touch the real network.

    ``detect_mcp_server`` performs up to five HTTP probes (10 s timeout each)
    and ``connect_mcp_server`` performs the MCP handshake — all against
    non-routable fake URLs like ``https://mcp.example.com/...``. Stub both at
    the ``mcp_service`` and ``router`` call sites so CRUD tests are fast and
    deterministic.
    """
    import importlib

    _router_mod = importlib.import_module("vendor_resources.router")
    _svc_mod = importlib.import_module("vendor_resources.services.mcp_service")

    async def fake_detect(server_url, **_kwargs):
        return {
            "ok": True,
            "server_url": server_url,
            "transport": "streamable_http",
            "endpoint": server_url,
            "reachable": False,
            "auth_required": False,
            "auth_type": "none",
            "confidence": "stub",
            "credential_fields": [],
            "hints": ["stubbed in tests"],
            "oauth_scopes": [],
            "error": None,
        }

    async def fake_connect(endpoint, credentials=None, transport=None, auth_type=None, **_kwargs):
        return {
            "transport": transport or "streamable_http",
            "bound_tools": [],
            "endpoint": endpoint,
        }

    monkeypatch.setattr(_svc_mod, "detect_mcp_server", fake_detect)
    monkeypatch.setattr(_svc_mod, "connect_mcp_server", fake_connect)
    # The router only calls detect directly (the connect endpoint delegates to
    # mcp_service.connect_registered_server, which is covered by the service
    # patch above); raising=False keeps this robust to import refactors.
    monkeypatch.setattr(_router_mod, "detect_mcp_server", fake_detect, raising=False)
    monkeypatch.setattr(_router_mod, "connect_mcp_server", fake_connect, raising=False)


# Isolated temp SQLite DB for the backend tests.
_TMPDIR = Path(tempfile.mkdtemp(prefix="backend-vr-test-"))
_TEST_URL = f"sqlite+aiosqlite:///{_TMPDIR / 'test.db'}"
os.environ.setdefault("DATABASE_URL", _TEST_URL)

from src.api.deps import CurrentUser, get_current_user  # noqa: E402
from src.core.roles import Roles  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import get_db  # noqa: E402
from src.models import *  # noqa: E402,F403

__import__("vendor_resources.models")

_test_engine = create_async_engine(_TEST_URL, echo=False)
_TestSessionLocal = async_sessionmaker(
    bind=_test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def _reset_db():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    await _reset_db()
    yield


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with _TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    from src.models import Tenant

    t = Tenant(id="tenant_test_01", name="Test Tenant", slug="test-tenant", status="active")
    db.add(t)
    await db.commit()
    return t


@pytest.fixture
def vendor_admin_user() -> CurrentUser:
    return CurrentUser(id="va_1", email="va@x.io", full_name="Vendor Admin", role=Roles.VENDOR_ADMIN)


@pytest.fixture
def solo_user() -> CurrentUser:
    return CurrentUser(id="solo_1", email="solo@x.io", full_name="Solo User", role=Roles.SOLO_USER)


@pytest.fixture
def tenant_user(tenant) -> CurrentUser:
    return CurrentUser(
        id="tu_1",
        email="tu@x.io",
        full_name="Tenant User",
        role=Roles.TENANT_USER,
        tenant_id=tenant.id,
    )


async def _client_for(user: CurrentUser):
    from apps.backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def admin_client(vendor_admin_user):
    async for ac in _client_for(vendor_admin_user):
        yield ac


@pytest_asyncio.fixture
async def solo_client(solo_user):
    async for ac in _client_for(solo_user):
        yield ac


@pytest_asyncio.fixture
async def tenant_client(tenant_user):
    async for ac in _client_for(tenant_user):
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    from apps.backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac