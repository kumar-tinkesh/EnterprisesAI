"""Pytest fixtures for the Vendor Resources (backend) tests.

Uses an isolated async SQLite engine (separate from the auth service's shared
engine) so a combined ``pytest`` run never contaminates the auth tests. The
backend app's ``get_db`` dependency is overridden per-app to yield sessions
from the test engine; the shared ``src.db.session`` module is left untouched.

We also override ``get_current_user`` directly with a :class:`CurrentUser`
instance per role; because ``require_roles`` depends on ``get_current_user``,
the override cascades to every admin-guarded route — no real JWTs or DB user
rows needed.
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

# Isolated temp SQLite DB for the backend tests.
_TMPDIR = Path(tempfile.mkdtemp(prefix="backend-vr-test-"))
_TEST_URL = f"sqlite+aiosqlite:///{_TMPDIR / 'test.db'}"
os.environ.setdefault("DATABASE_URL", _TEST_URL)

from src.api.deps import CurrentUser, get_current_user  # noqa: E402
from src.core.roles import Roles  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import get_db  # noqa: E402
from src.models import *  # noqa: E402,F403  (register auth tables on metadata)

import vendor_resources.models  # noqa: E402,F401  (register vendor tables)
import vendor_resources.services.embeddings as _embeddings  # noqa: E402
from apps.llm_gateway.exceptions import ProviderNotConfiguredError  # noqa: E402
from apps.llm_gateway.types import (  # noqa: E402
    CompletionResponse,
    EmbeddingResponse,
    TokenUsage,
)

_test_engine = create_async_engine(_TEST_URL, echo=False)
_TestSessionLocal = async_sessionmaker(
    bind=_test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


# ── gateway neutralisation ───────────────────────────────────────────────────
# By default, no real LLM calls happen in tests: embed_text() degrades to None.
# Tests that need semantic behaviour opt into the `mock_gateway` fixture below.
class _NoEmbedGateway:
    async def embed(self, *_a, **_kw):
        raise ProviderNotConfiguredError("no provider in tests")

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def _disable_real_embed(monkeypatch):
    monkeypatch.setattr(_embeddings, "get_gateway", lambda: _NoEmbedGateway())


# ── database lifecycle ───────────────────────────────────────────────────────


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


# ── domain data ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    from src.models import Tenant

    t = Tenant(id="tenant_test_01", name="Test Tenant", slug="test-tenant", status="active")
    db.add(t)
    await db.commit()
    return t


# ── role identities ──────────────────────────────────────────────────────────


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


# ── HTTP clients with auth + DB overrides ────────────────────────────────────


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSessionLocal() as session:
        yield session


async def _client_for(user: CurrentUser):
    from apps.backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


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
    """A client with NO auth override — real get_current_user runs (401 without token)."""
    from apps.backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ── deterministic embedding mock ─────────────────────────────────────────────
# Maps keywords to one-hot axes so cosine ranking is predictable without real
# API keys. Both tool text ("name\ndescription") and the query are embedded with
# the same fake, so shared keywords → high cosine.
_KEYWORD_AXES: dict[str, int] = {
    "invoice": 0,
    "employee": 1,
    "email": 2,
    "finance": 3,
    "hr": 4,
    "notification": 5,
    "send": 6,
    "lookup": 7,
    "retrieve": 8,
    "payment": 9,
}
_MOCK_DIM = 16


def _keyword_vector(text: str) -> list[float]:
    low = (text or "").lower()
    vec = [0.0] * _MOCK_DIM
    for kw, axis in _KEYWORD_AXES.items():
        if kw in low:
            vec[axis] = 1.0
    return vec


class _MockGateway:
    async def embed(self, texts, *, model=None, provider=None):
        return EmbeddingResponse(
            embeddings=[_keyword_vector(t) for t in texts],
            model="mock-embed",
            provider="mock",
            usage=TokenUsage(prompt_tokens=1, total_tokens=1),
        )

    async def close(self):
        pass


@pytest.fixture
def mock_gateway(monkeypatch):
    """Opt-in: make embeddings.get_gateway return a deterministic fake."""
    monkeypatch.setattr(_embeddings, "get_gateway", lambda: _MockGateway())
    return _MockGateway()


# ── mock LLM for the AI Compiler (embed + complete) ──────────────────────────
import re as _re  # noqa: E402

_UUID_RE = _re.compile(r'"id":\s*"([0-9a-fA-F-]{36})"')


def _spec_json_for_prompt(prompt: str) -> str:
    """Extract the first tool id from the compiler prompt and emit a 1-node spec."""
    m = _UUID_RE.search(prompt or "")
    tool_id = m.group(1) if m else None
    node = {"id": "n1", "node_type": "tool.call", "tool_id": tool_id, "args": {}, "description": "compiled"}
    if tool_id is None:
        node["unconfigured"] = True
    import json as _json

    return _json.dumps(
        {
            "agent_name": "compiled_agent",
            "description": "mock-compiled plan",
            "nodes": [node],
            "edges": [],
        }
    )


class _MockLLMGateway:
    """Fake gateway with deterministic embed (keyword vectors) + complete (spec JSON)."""

    def __init__(self, complete_content=None) -> None:
        # complete_content: if set, returned verbatim (used by per-test fakes)
        self._override = complete_content
        self.complete_calls = 0

    async def embed(self, texts, *, model=None, provider=None):
        return EmbeddingResponse(
            embeddings=[_keyword_vector(t) for t in texts],
            model="mock-embed",
            provider="mock",
            usage=TokenUsage(prompt_tokens=1, total_tokens=1),
        )

    async def complete(self, request, *, provider=None, fallback=True):
        self.complete_calls += 1
        if self._override is not None:
            content = self._override
        else:
            # Build a spec from the tool ids present in the system prompt.
            sys_msg = next((m.content for m in request.messages if m.role.value == "system"), "")
            content = _spec_json_for_prompt(sys_msg)
        return CompletionResponse(content=content, model="mock-llm", provider="mock")

    async def close(self):
        pass


@pytest.fixture
def mock_llm(monkeypatch):
    """Opt-in: a fake gateway backing both semantic embed and compiler complete."""
    gw = _MockLLMGateway()
    monkeypatch.setattr(_embeddings, "get_gateway", lambda: gw)
    return gw