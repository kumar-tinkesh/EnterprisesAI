"""Tests for the generic "Connect via OAuth" authorization-code flow.

Covers: manually configuring OAuth endpoints (for servers whose metadata
can't be auto-discovered), building the authorize URL, the provider
callback completing the exchange and persisting credentials (including
fuzzy-matching a provider-specific extra callback param like Intuit's
``realmId`` against a server's own detected field name), replay rejection,
and that non-oauth2 servers are completely unaffected.
"""
from __future__ import annotations

import pytest

from vendor_resources.services import mcp_auth

BASE = "/api/v1/vendor/resources"


def _mcp_payload(name="quickbooks.mcp", is_global=True):
    return {
        "name": name,
        "description": "QuickBooks Online MCP server.",
        "source_url": "https://mcp.example.com/quickbooks",
        "is_global": is_global,
    }


def _oauth_config_payload():
    return {
        "authorization_endpoint": "https://appcenter.intuit.com/connect/oauth2",
        "token_endpoint": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "scope": "com.intuit.quickbooks.accounting",
    }


async def _create_server(admin_client) -> str:
    res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload())
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ── PATCH /mcp/{id}/oauth-config ─────────────────────────────────────


@pytest.mark.asyncio
async def test_set_oauth_config_as_admin(admin_client):
    server_id = await _create_server(admin_client)
    res = await admin_client.patch(
        f"{BASE}/mcp/{server_id}/oauth-config", json=_oauth_config_payload()
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["auth_type"] == "oauth2"
    assert body["auth_config"]["oauth"]["authorization_endpoint"] == (
        "https://appcenter.intuit.com/connect/oauth2"
    )
    assert body["auth_config"]["oauth"]["scopes_supported"] == [
        "com.intuit.quickbooks.accounting"
    ]


@pytest.mark.asyncio
async def test_set_oauth_config_forbidden_for_solo_user(solo_client, admin_client):
    server_id = await _create_server(admin_client)
    res = await solo_client.patch(
        f"{BASE}/mcp/{server_id}/oauth-config", json=_oauth_config_payload()
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_set_oauth_config_404_for_unknown_server(admin_client):
    res = await admin_client.patch(
        f"{BASE}/mcp/does-not-exist/oauth-config", json=_oauth_config_payload()
    )
    assert res.status_code == 404


# ── POST /mcp/{id}/oauth/authorize ───────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_requires_oauth_config_first(admin_client):
    """No PATCH /oauth-config yet -> clear 400, not a confusing crash."""
    server_id = await _create_server(admin_client)
    res = await admin_client.post(
        f"{BASE}/mcp/{server_id}/oauth/authorize",
        json={"client_id": "CID", "client_secret": "SEC"},
    )
    assert res.status_code == 400
    assert "authorization_endpoint" in res.json()["detail"]


@pytest.mark.asyncio
async def test_authorize_builds_valid_url(admin_client):
    server_id = await _create_server(admin_client)
    await admin_client.patch(f"{BASE}/mcp/{server_id}/oauth-config", json=_oauth_config_payload())

    res = await admin_client.post(
        f"{BASE}/mcp/{server_id}/oauth/authorize",
        json={"client_id": "CID123", "client_secret": "SEC456"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["authorization_url"].startswith(
        "https://appcenter.intuit.com/connect/oauth2?"
    )
    assert "client_id=CID123" in body["authorization_url"]
    assert f"state={body['state']}" in body["authorization_url"]
    assert "redirect_uri=" in body["authorization_url"]
    assert "com.intuit.quickbooks.accounting" in body["authorization_url"]


# ── GET /mcp/oauth/callback ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_completes_flow_and_matches_extra_param(
    admin_client, anon_client, monkeypatch, db
):
    server_id = await _create_server(admin_client)
    await admin_client.patch(f"{BASE}/mcp/{server_id}/oauth-config", json=_oauth_config_payload())
    # Simulate what repo detection would have found for this server: its
    # own credential field names, so the extra 'realmId' callback param can
    # be fuzzy-matched against QUICKBOOKS_REALM_ID (covered in isolation by
    # test_repo_analyzer.py; this test only covers the OAuth flow itself).
    from vendor_resources.services.mcp_service import get_mcp_server

    server_row = await get_mcp_server(db, server_id=server_id)
    server_row.auth_schema = {
        "fields": [
            {"name": "QUICKBOOKS_CLIENT_ID"},
            {"name": "QUICKBOOKS_CLIENT_SECRET"},
            {"name": "QUICKBOOKS_REALM_ID"},
            {"name": "QUICKBOOKS_REFRESH_TOKEN"},
        ]
    }
    await db.commit()

    authorize_res = await admin_client.post(
        f"{BASE}/mcp/{server_id}/oauth/authorize",
        json={"client_id": "CID123", "client_secret": "SEC456"},
    )
    state = authorize_res.json()["state"]

    async def fake_exchange(oauth, credentials, *, code, redirect_uri):
        assert code == "AUTHCODE1"
        assert redirect_uri.endswith("/mcp/oauth/callback")
        return {"access_token": "ACCESS1", "refresh_token": "REFRESH1"}

    monkeypatch.setattr(mcp_auth, "exchange_authorization_code", fake_exchange)

    # Intuit-style callback: code + state + its own extra 'realmId' param.
    callback_res = await anon_client.get(
        f"{BASE}/mcp/oauth/callback",
        params={"code": "AUTHCODE1", "state": state, "realmId": "9130354312345678"},
    )
    assert callback_res.status_code == 200, callback_res.text
    assert "Connected" in callback_res.text

    stored = await mcp_auth.load_server_credentials(db, server_id=server_id)
    assert stored["client_id"] == "CID123"
    assert stored["client_secret"] == "SEC456"
    assert stored["access_token"] == "ACCESS1"
    assert stored["refresh_token"] == "REFRESH1"
    # The provider's own camelCase param name is kept as-is...
    assert stored["realmId"] == "9130354312345678"
    # ...and also mapped onto this server's real, detected field name.
    assert stored["QUICKBOOKS_REALM_ID"] == "9130354312345678"


@pytest.mark.asyncio
async def test_callback_rejects_replayed_state(admin_client, anon_client, monkeypatch):
    server_id = await _create_server(admin_client)
    await admin_client.patch(f"{BASE}/mcp/{server_id}/oauth-config", json=_oauth_config_payload())
    authorize_res = await admin_client.post(
        f"{BASE}/mcp/{server_id}/oauth/authorize",
        json={"client_id": "CID123", "client_secret": "SEC456"},
    )
    state = authorize_res.json()["state"]

    async def fake_exchange(oauth, credentials, *, code, redirect_uri):
        return {"access_token": "ACCESS1", "refresh_token": "REFRESH1"}

    monkeypatch.setattr(mcp_auth, "exchange_authorization_code", fake_exchange)

    first = await anon_client.get(
        f"{BASE}/mcp/oauth/callback", params={"code": "C1", "state": state}
    )
    assert first.status_code == 200

    replay = await anon_client.get(
        f"{BASE}/mcp/oauth/callback", params={"code": "C1", "state": state}
    )
    assert replay.status_code == 400
    assert "Connection failed" in replay.text


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state(anon_client):
    res = await anon_client.get(
        f"{BASE}/mcp/oauth/callback", params={"code": "C1", "state": "not-a-real-state"}
    )
    assert res.status_code == 400
    assert "Connection failed" in res.text


@pytest.mark.asyncio
async def test_callback_missing_code_or_state(anon_client):
    res = await anon_client.get(f"{BASE}/mcp/oauth/callback")
    assert res.status_code == 400
