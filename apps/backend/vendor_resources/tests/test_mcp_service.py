"""Service-level tests for the Vendor Resources subsystem (MCP).

Covers the catalog engine access-filter logic across roles, MCP
creation + audit, and grant validation — directly against the
async session, no HTTP.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.api.deps import CurrentUser
from src.core.roles import Roles
from src.models import Tenant

from vendor_resources.models import TenantResourceGrant, VendorMCPServer
from vendor_resources.schemas import ConnectMCPServerRequest, GrantTenantResourceRequest
from vendor_resources.services.catalog_engine import (
    get_authorized_vendor_catalog,
)
from vendor_resources.services.mcp_service import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    grant_resource,
    list_mcp_servers,
)


def _make_user(role: str, tenant_id: str | None = None) -> CurrentUser:
    return CurrentUser(
        id=f"u_{role}", email=f"{role}@x.io", full_name=role, role=role, tenant_id=tenant_id
    )


async def _make_mcp(db, name: str, is_global: bool) -> VendorMCPServer:
    server = await create_mcp_server(
        db,
        data=ConnectMCPServerRequest(
            name=name,
            description=f"desc {name}",
            transport="sse",
            server_url=f"https://mcp.example.com/{name}",
            is_global=is_global,
        ),
        actor_id="va_1",
    )
    await db.commit()
    await db.refresh(server)
    return server


# ── catalog access filtering ───────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_admin_sees_all(db):
    await _make_mcp(db, "admin.glob", is_global=True)
    await _make_mcp(db, "admin.priv", is_global=False)
    servers = await get_authorized_vendor_catalog(db, user=_make_user(Roles.VENDOR_ADMIN))
    names = {s.name for s in servers}
    assert {"admin.glob", "admin.priv"}.issubset(names)


@pytest.mark.asyncio
async def test_catalog_solo_sees_only_global(db):
    await _make_mcp(db, "solo.glob", is_global=True)
    await _make_mcp(db, "solo.priv", is_global=False)
    servers = await get_authorized_vendor_catalog(db, user=_make_user(Roles.SOLO_USER))
    names = {s.name for s in servers}
    assert "solo.glob" in names
    assert "solo.priv" not in names


@pytest.mark.asyncio
async def test_catalog_tenant_sees_globals_plus_granted(db):
    tenant = Tenant(id="tenant_svc_01", name="T", slug="t-slug", status="active")
    db.add(tenant)
    await db.commit()
    glob = await _make_mcp(db, "ten.glob", is_global=True)
    priv = await _make_mcp(db, "ten.priv", is_global=False)
    await _make_mcp(db, "ten.other_priv", is_global=False)

    await grant_resource(
        db,
        data=GrantTenantResourceRequest(
            tenant_id=tenant.id, resource_type="mcp", resource_id=priv.id
        ),
        actor_id="va_1",
    )
    await db.commit()

    servers = await get_authorized_vendor_catalog(
        db, user=_make_user(Roles.TENANT_USER, tenant_id=tenant.id)
    )
    names = {s.name for s in servers}
    assert "ten.glob" in names
    assert "ten.priv" in names
    assert "ten.other_priv" not in names
    assert glob.name in names


# ── MCP create + audit ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_mcp_records_audit(db):
    await create_mcp_server(
        db,
        data=ConnectMCPServerRequest(
            name="audit.mcp",
            description="d",
            transport="sse",
            server_url="https://mcp.example.com/audit",
            is_global=True,
        ),
        actor_id="va_1",
    )
    await db.commit()

    from src.models import AuditEvent

    events = (
        await db.execute(select(AuditEvent).where(AuditEvent.action == "mcp_server.create"))
    ).scalars().all()
    assert len(events) == 1
    assert events[0].resource.startswith("mcp_server:")
    assert events[0].user_id == "va_1"


# ── grant validation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_validates_tenant_exists(db):
    mcp = await _make_mcp(db, "grant.notenant", is_global=False)
    with pytest.raises(LookupError):
        await grant_resource(
            db,
            data=GrantTenantResourceRequest(
                tenant_id="missing-tenant", resource_type="mcp", resource_id=mcp.id
            ),
            actor_id="va_1",
        )


@pytest.mark.asyncio
async def test_grant_validates_resource_exists(db):
    tenant = Tenant(id="tenant_svc_02", name="T2", slug="t2-slug", status="active")
    db.add(tenant)
    await db.commit()
    with pytest.raises(LookupError):
        await grant_resource(
            db,
            data=GrantTenantResourceRequest(
                tenant_id=tenant.id, resource_type="mcp", resource_id="missing-mcp"
            ),
            actor_id="va_1",
        )


@pytest.mark.asyncio
async def test_grant_unsupported_resource_type(db):
    tenant = Tenant(id="tenant_svc_03", name="T3", slug="t3-slug", status="active")
    db.add(tenant)
    await db.commit()
    with pytest.raises(ValueError):
        await grant_resource(
            db,
            data=GrantTenantResourceRequest(
                tenant_id=tenant.id, resource_type="tool", resource_id="whatever"
            ),
            actor_id="va_1",
        )


# ── delete cascade ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_mcp_removes_grants(db):
    tenant = Tenant(id="tenant_svc_04", name="T4", slug="t4-slug", status="active")
    db.add(tenant)
    await db.commit()
    mcp = await _make_mcp(db, "del.cascade", is_global=False)
    await grant_resource(
        db,
        data=GrantTenantResourceRequest(
            tenant_id=tenant.id, resource_type="mcp", resource_id=mcp.id
        ),
        actor_id="va_1",
    )
    await db.commit()

    await delete_mcp_server(db, server_id=mcp.id, actor_id="va_1")
    await db.commit()

    remaining = (
        await db.execute(
            select(TenantResourceGrant).where(TenantResourceGrant.resource_id == mcp.id)
        )
    ).scalars().all()
    assert remaining == []

    row = (
        await db.execute(select(VendorMCPServer).where(VendorMCPServer.id == mcp.id))
    ).scalars().first()
    assert row is None


@pytest.mark.asyncio
async def test_delete_mcp_returns_false_when_missing(db):
    assert await delete_mcp_server(db, server_id="nope", actor_id="va_1") is False


# ── list MCP servers ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_mcp_servers(db):
    await _make_mcp(db, "list.1", is_global=True)
    await _make_mcp(db, "list.2", is_global=False)
    servers = await list_mcp_servers(db)
    names = {s.name for s in servers}
    assert {"list.1", "list.2"}.issubset(names)


# ── get MCP server ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_mcp_server(db):
    mcp = await _make_mcp(db, "get.test", is_global=True)
    found = await get_mcp_server(db, mcp.id)
    assert found is not None
    assert found.name == "get.test"


@pytest.mark.asyncio
async def test_get_mcp_server_missing(db):
    found = await get_mcp_server(db, "nonexistent-id")
    assert found is None