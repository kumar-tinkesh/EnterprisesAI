"""Fixtures shared by the builder tests (on top of apps/backend/conftest.py)."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db


@pytest_asyncio.fixture
async def make_user_client(db):
    """A client authenticated as any ``CurrentUser`` (the shared conftest only has fixed ones)."""
    from apps.backend.main import create_app

    maker = async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with maker() as session:
            yield session

    clients: list[AsyncClient] = []

    async def build(user: CurrentUser) -> AsyncClient:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = override_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(client)
        return client

    yield build
    for c in clients:
        await c.aclose()
