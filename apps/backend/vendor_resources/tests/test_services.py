"""Service-level tests for the Vendor Resources subsystem.

Covers the catalog engine access-filter logic across roles, tool creation +
audit, grant validation, and the AES vault round-trip — directly against the
async session, no HTTP.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.api.deps import CurrentUser
from src.core.roles import Roles
from src.models import AuditEvent, Tenant

from vendor_resources.core.vault import Vault, generate_key
from vendor_resources.models import TenantResourceGrant, ToolEmbedding, VendorTool
from vendor_resources.schemas import CreateVendorToolRequest, GrantTenantResourceRequest
from vendor_resources.services.catalog_engine import (
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
)
from vendor_resources.services.tool_service import (
    create_tool,
    delete_tool,
    embed_tool,
    grant_resource,
)


def _make_user(role: str, tenant_id: str | None = None) -> CurrentUser:
    return CurrentUser(
        id=f"u_{role}", email=f"{role}@x.io", full_name=role, role=role, tenant_id=tenant_id
    )


async def _make_tool(db, name: str, is_global: bool) -> VendorTool:
    tool = await create_tool(
        db,
        data=CreateVendorToolRequest(
            name=name,
            description=f"desc {name}",
            category="finance",
            method="GET",
            parameters_schema={"type": "object"},
            is_global=is_global,
        ),
        actor_id="va_1",
    )
    await db.commit()
    await db.refresh(tool)
    return tool


@pytest.mark.asyncio
async def test_vault_encrypt_decrypt_roundtrip():
    vault = Vault(generate_key())
    token = vault.encrypt("super-secret-api-key")
    assert token.startswith("v1:")
    assert vault.decrypt(token) == "super-secret-api-key"
    assert "super-secret-api-key" not in token


def test_vault_rejects_bad_key_length():
    import base64

    with pytest.raises(ValueError):
        Vault(base64.urlsafe_b64encode(b"too-short").decode())


@pytest.mark.asyncio
async def test_vault_dev_key_is_deterministic():
    a = Vault("")  # dev fallback
    b = Vault("")
    token = a.encrypt("x")
    assert b.decrypt(token) == "x"


# ── catalog access filtering ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_admin_sees_all(db):
    await _make_tool(db, "admin.glob", is_global=True)
    await _make_tool(db, "admin.priv", is_global=False)
    tools = await get_authorized_vendor_catalog(db, user=_make_user(Roles.VENDOR_ADMIN))
    names = {t.name for t in tools}
    assert {"admin.glob", "admin.priv"}.issubset(names)


@pytest.mark.asyncio
async def test_catalog_solo_sees_only_global(db):
    await _make_tool(db, "solo.glob", is_global=True)
    await _make_tool(db, "solo.priv", is_global=False)
    tools = await get_authorized_vendor_catalog(db, user=_make_user(Roles.SOLO_USER))
    names = {t.name for t in tools}
    assert "solo.glob" in names
    assert "solo.priv" not in names


@pytest.mark.asyncio
async def test_catalog_tenant_sees_globals_plus_granted(db):
    tenant = Tenant(id="tenant_svc_01", name="T", slug="t-slug", status="active")
    db.add(tenant)
    glob = await _make_tool(db, "ten.glob", is_global=True)
    priv = await _make_tool(db, "ten.priv", is_global=False)
    other_priv = await _make_tool(db, "ten.other_priv", is_global=False)

    await grant_resource(
        db,
        data=GrantTenantResourceRequest(
            tenant_id=tenant.id, resource_type="vendor_tool", resource_id=priv.id
        ),
        actor_id="va_1",
    )
    await db.commit()

    tools = await get_authorized_vendor_catalog(
        db, user=_make_user(Roles.TENANT_USER, tenant_id=tenant.id)
    )
    names = {t.name for t in tools}
    assert "ten.glob" in names
    assert "ten.priv" in names
    assert "ten.other_priv" not in names
    # sanity: the global we created is the one returned
    assert glob.name in names


@pytest.mark.asyncio
async def test_catalog_semantic_without_gateway_falls_back(db):
    """No embeddings available → semantic returns the access-filtered list."""
    await _make_tool(db, "sem.glob1", is_global=True)
    await _make_tool(db, "sem.glob2", is_global=True)
    tools = await get_authorized_vendor_catalog_semantic(
        db, user=_make_user(Roles.SOLO_USER), query="anything", top_k=5
    )
    names = {t.name for t in tools}
    assert {"sem.glob1", "sem.glob2"}.issubset(names)


@pytest.mark.asyncio
async def test_catalog_semantic_ranks_relevant_tool_first(db, mock_gateway):
    invoice = await _make_tool(db, "finance.getInvoice", is_global=True)
    await _make_tool(db, "hr.lookupEmployee", is_global=True)

    ranked = await get_authorized_vendor_catalog_semantic(
        db, user=_make_user(Roles.SOLO_USER), query="show me invoices", top_k=5
    )
    assert ranked[0].id == invoice.id


@pytest.mark.asyncio
async def test_catalog_semantic_respects_access_control(db, mock_gateway, tenant):
    # A non-global, invoice-flavoured tool that is NOT granted to the tenant.
    private = await _make_tool(db, "finance.privateInvoice", is_global=False)
    private.description = "Retrieve a private vendor invoice."
    await db.commit()
    # An embedding exists for it (via mock_gateway on create) — but solo user
    # must NOT see it because access-filtering runs before ranking.
    ranked = await get_authorized_vendor_catalog_semantic(
        db, user=_make_user(Roles.SOLO_USER), query="invoice", top_k=5
    )
    ids = {t.id for t in ranked}
    assert private.id not in ids


@pytest.mark.asyncio
async def test_catalog_semantic_top_k_truncation(db, mock_gateway):
    for i in range(6):
        await _make_tool(db, f"finance.invoice{i}", is_global=True)
    ranked = await get_authorized_vendor_catalog_semantic(
        db, user=_make_user(Roles.SOLO_USER), query="invoice", top_k=3
    )
    assert len(ranked) == 3


# ── embed-on-create + embed_tool ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tool_with_gateway_stores_embedding(db, mock_gateway):
    tool = await _make_tool(db, "finance.getInvoice", is_global=True)
    row = (
        await db.execute(select(ToolEmbedding).where(ToolEmbedding.tool_id == tool.id))
    ).scalars().first()
    assert row is not None
    assert row.model == "mock-embed"
    assert row.dim == len(row.embedding)
    assert row.dim > 0


@pytest.mark.asyncio
async def test_create_tool_without_gateway_has_no_embedding(db):
    # default conftest disables the gateway → no embedding row, tool still created
    tool = await _make_tool(db, "noembed.tool", is_global=True)
    row = (
        await db.execute(select(ToolEmbedding).where(ToolEmbedding.tool_id == tool.id))
    ).scalars().first()
    assert row is None
    assert tool.name == "noembed.tool"


@pytest.mark.asyncio
async def test_embed_tool_reembeds_and_audits(db, mock_gateway):
    from sqlalchemy import delete as sa_delete

    tool = await _make_tool(db, "finance.reembed", is_global=True)
    # remove the embedding created on create, then re-embed via the service
    await db.execute(sa_delete(ToolEmbedding).where(ToolEmbedding.tool_id == tool.id))
    await db.commit()

    ok = await embed_tool(db, tool_id=tool.id, actor_id="va_1")
    await db.commit()
    assert ok is True
    row = (
        await db.execute(select(ToolEmbedding).where(ToolEmbedding.tool_id == tool.id))
    ).scalars().first()
    assert row is not None

    events = (
        await db.execute(select(AuditEvent).where(AuditEvent.action == "vendor_tool.embed"))
    ).scalars().all()
    assert any(e.resource == f"vendor_tool:{tool.id}" for e in events)


@pytest.mark.asyncio
async def test_embed_tool_missing_returns_false(db, mock_gateway):
    assert await embed_tool(db, tool_id="nope", actor_id="va_1") is False


# ── tool create + audit ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tool_records_audit(db):
    await create_tool(
        db,
        data=CreateVendorToolRequest(
            name="audit.tool",
            description="d",
            category="hr",
            method="POST",
            parameters_schema={},
            is_global=True,
        ),
        actor_id="va_1",
    )
    await db.commit()

    events = (
        await db.execute(select(AuditEvent).where(AuditEvent.action == "vendor_tool.create"))
    ).scalars().all()
    assert len(events) == 1
    assert events[0].resource.startswith("vendor_tool:")
    assert events[0].user_id == "va_1"


# ── grant validation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_validates_tenant_exists(db):
    tool = await _make_tool(db, "grant.notenant", is_global=False)
    with pytest.raises(LookupError):
        await grant_resource(
            db,
            data=GrantTenantResourceRequest(
                tenant_id="missing-tenant", resource_type="vendor_tool", resource_id=tool.id
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
                tenant_id=tenant.id, resource_type="vendor_tool", resource_id="missing-tool"
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
                tenant_id=tenant.id, resource_type="mcp_server", resource_id="whatever"
            ),
            actor_id="va_1",
        )


# ── delete cascade ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_tool_removes_grants(db):
    tenant = Tenant(id="tenant_svc_04", name="T4", slug="t4-slug", status="active")
    db.add(tenant)
    await db.commit()
    tool = await _make_tool(db, "del.cascade", is_global=False)
    await grant_resource(
        db,
        data=GrantTenantResourceRequest(
            tenant_id=tenant.id, resource_type="vendor_tool", resource_id=tool.id
        ),
        actor_id="va_1",
    )
    await db.commit()

    await delete_tool(db, tool_id=tool.id, actor_id="va_1")
    await db.commit()

    remaining = (
        await db.execute(
            select(TenantResourceGrant).where(TenantResourceGrant.resource_id == tool.id)
        )
    ).scalars().all()
    assert remaining == []

    tool_row = (
        await db.execute(select(VendorTool).where(VendorTool.id == tool.id))
    ).scalars().first()
    assert tool_row is None


@pytest.mark.asyncio
async def test_delete_tool_returns_false_when_missing(db):
    assert await delete_tool(db, tool_id="nope", actor_id="va_1") is False