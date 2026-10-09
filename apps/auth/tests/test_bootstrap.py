"""The first platform admin, created from ADMIN_EMAIL / ADMIN_PASSWORD on startup."""
from __future__ import annotations

from sqlalchemy import select

from src.config import Settings
from src.core.bootstrap import ensure_admin, ensure_tenant
from src.core.security import verify_password
from src.models.tenant import VendorUser


def cfg(**values) -> Settings:
    return Settings(_env_file=None, **values)


async def test_creates_the_admin_once_and_never_resets_it(db, client):
    settings = cfg(ADMIN_EMAIL=" Admin@Acme.io ", ADMIN_PASSWORD="first-pass-123", ADMIN_FULL_NAME="Ops Admin")
    assert await ensure_admin(db, settings) == "created"

    login = await client.post("/api/v1/auth/login", json={"email": "admin@acme.io", "password": "first-pass-123"})
    assert login.status_code == 200, login.text
    token = login.json().get("access_token") or login.json()["tokens"]["access_token"]
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
    assert (me["email"], me["role"]) == ("admin@acme.io", "vendor_admin")

    # A restart (even with a different password in .env) leaves the account alone.
    again = cfg(ADMIN_EMAIL="admin@acme.io", ADMIN_PASSWORD="another-pass-456")
    assert await ensure_admin(db, again) == "exists"
    [admin] = (await db.execute(select(VendorUser))).scalars().all()
    assert admin.full_name == "Ops Admin" and verify_password("first-pass-123", admin.hashed_password)


async def test_not_configured_or_too_short_is_skipped(db):
    assert await ensure_admin(db, cfg()) == "skipped"
    assert await ensure_admin(db, cfg(ADMIN_EMAIL="a@b.io")) == "skipped"
    assert await ensure_admin(db, cfg(ADMIN_EMAIL="a@b.io", ADMIN_PASSWORD="short")) == "skipped"
    # Login rejects reserved domains, so such an admin could never sign in.
    assert await ensure_admin(db, cfg(ADMIN_EMAIL="admin@company.local", ADMIN_PASSWORD="long-enough-1")) == "skipped"
    assert (await db.execute(select(VendorUser))).scalars().first() is None


async def test_creates_the_first_tenant_with_its_admin(db, client):
    from src.models.tenant import Tenant
    from src.models.workspace import Workspace

    settings = cfg(TENANT_NAME="Acme Corp", TENANT_ADMIN_EMAIL="Boss@Acme.io", TENANT_ADMIN_PASSWORD="tenant-pass-1", TENANT_ADMIN_FULL_NAME="Boss")
    assert await ensure_tenant(db, settings) == "created"
    assert await ensure_tenant(db, settings) == "exists"
    [tenant] = (await db.execute(select(Tenant))).scalars().all()
    assert (tenant.name, tenant.is_personal) == ("Acme Corp", False)
    assert len((await db.execute(select(Workspace))).scalars().all()) == 1

    login = await client.post("/api/v1/auth/login", json={"email": "boss@acme.io", "password": "tenant-pass-1"})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["role"] == "tenant_admin"

    assert await ensure_tenant(db, cfg(TENANT_NAME="X", TENANT_ADMIN_EMAIL="x@y.io")) == "skipped"
