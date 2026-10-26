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

from vendor.services import mcp_auth

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


async def _create_server(admin_client, *, is_global: bool = True) -> str:
    res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload(is_global=is_global))
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
    from vendor.services.mcp_service import get_mcp_server

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


# ── Saving the app's client_id/secret via oauth-config (for reuse) ────


@pytest.mark.asyncio
async def test_oauth_config_persists_app_credentials_for_reuse(admin_client, db):
    """PATCH .../oauth-config with client_id/secret -> saved encrypted on
    the server's shared credential row, not just endpoints."""
    server_id = await _create_server(admin_client)
    payload = {**_oauth_config_payload(), "client_id": "APPCID", "client_secret": "APPSEC"}
    res = await admin_client.patch(f"{BASE}/mcp/{server_id}/oauth-config", json=payload)
    assert res.status_code == 200, res.text

    stored = await mcp_auth.load_server_credentials(db, server_id=server_id, tenant_id=None)
    assert stored["oauth_client_id"] == "APPCID"
    assert stored["oauth_client_secret"] == "APPSEC"


@pytest.mark.asyncio
async def test_authorize_reuses_stored_app_credentials(admin_client):
    """Admin's own authorize call can omit client_id/secret once they're saved."""
    server_id = await _create_server(admin_client)
    await admin_client.patch(
        f"{BASE}/mcp/{server_id}/oauth-config",
        json={**_oauth_config_payload(), "client_id": "APPCID", "client_secret": "APPSEC"},
    )
    res = await admin_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize", json={})
    assert res.status_code == 200, res.text
    assert "client_id=APPCID" in res.json()["authorization_url"]


# ── End-user self-service "Connect via OAuth" (authorize-as-user) ─────


async def _verified_oauth_server(admin_client, db, *, with_app_credentials=True) -> str:
    server_id = await _create_server(admin_client, is_global=True)
    payload = dict(_oauth_config_payload())
    if with_app_credentials:
        payload.update(client_id="APPCID", client_secret="APPSEC")
    await admin_client.patch(f"{BASE}/mcp/{server_id}/oauth-config", json=payload)

    from vendor.services.mcp_service import get_mcp_server

    server_row = await get_mcp_server(db, server_id=server_id)
    server_row.status = "VERIFIED"
    await db.commit()
    return server_id


@pytest.mark.asyncio
async def test_authorize_as_user_rejects_non_oauth_server(tenant_client, admin_client):
    server_id = await _create_server(admin_client, is_global=True)
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 400
    assert "doesn't use OAuth" in res.json()["detail"]


@pytest.mark.asyncio
async def test_authorize_as_user_rejects_unverified_server(tenant_client, admin_client):
    server_id = await _create_server(admin_client, is_global=True)
    await admin_client.patch(
        f"{BASE}/mcp/{server_id}/oauth-config",
        json={**_oauth_config_payload(), "client_id": "APPCID", "client_secret": "APPSEC"},
    )
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_authorize_as_user_requires_admin_configured_app_credentials(
    tenant_client, admin_client, db
):
    """An end-user must never be asked for (or able to supply) the app's
    client_secret — if the admin never saved one, this fails clearly."""
    server_id = await _verified_oauth_server(admin_client, db, with_app_credentials=False)
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 400
    assert "vendor admin must set them" in res.json()["detail"]


@pytest.mark.asyncio
async def test_authorize_as_user_forbidden_for_invisible_server(solo_client, admin_client, db):
    """A restricted (non-global, ungranted) server stays invisible to the
    connect-as-user OAuth path exactly like the plain connect-as-user one."""
    server_id = await _create_server(admin_client, is_global=False)
    await admin_client.patch(
        f"{BASE}/mcp/{server_id}/oauth-config",
        json={**_oauth_config_payload(), "client_id": "APPCID", "client_secret": "APPSEC"},
    )
    res = await solo_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_authorize_as_user_builds_url_without_exposing_secret(tenant_client, admin_client, db):
    server_id = await _verified_oauth_server(admin_client, db)
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert "client_id=APPCID" in body["authorization_url"]
    # The app secret is never round-tripped to the end-user's browser.
    assert "APPSEC" not in body["authorization_url"]
    assert "state" in body


@pytest.mark.asyncio
async def test_callback_from_user_flow_stores_isolated_user_credential(
    tenant_client, admin_client, anon_client, monkeypatch, db, tenant
):
    """The tokens from an end-user-initiated OAuth flow land in *that
    user's own* isolated credential row — never the vendor's shared one."""
    server_id = await _verified_oauth_server(admin_client, db)

    authorize_res = await tenant_client.post(
        f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={}
    )
    state = authorize_res.json()["state"]

    async def fake_exchange(oauth, credentials, *, code, redirect_uri):
        return {"access_token": "USERACCESS1", "refresh_token": "USERREFRESH1"}

    monkeypatch.setattr(mcp_auth, "exchange_authorization_code", fake_exchange)

    callback_res = await anon_client.get(
        f"{BASE}/mcp/oauth/callback", params={"code": "C1", "state": state}
    )
    assert callback_res.status_code == 200, callback_res.text

    user_creds = await mcp_auth.load_server_credentials(
        db, server_id=server_id, tenant_id=tenant.id, user_id="tu_1"
    )
    assert user_creds["access_token"] == "USERACCESS1"

    shared_creds = await mcp_auth.load_server_credentials(db, server_id=server_id, tenant_id=None)
    # The shared row still only has the app's own client credentials —
    # this user's freshly-issued tokens must not have landed there.
    assert "access_token" not in shared_creds
    assert shared_creds["oauth_client_id"] == "APPCID"


# ── Self-registering servers: RFC 7591 client + PKCE (Atlassian-style) ──


_DCR_OAUTH = {
    "authorization_endpoint": "https://auth.example.com/authorize",
    "token_endpoint": "https://auth.example.com/oauth/token",
    "registration_endpoint": "https://auth.example.com/dcr/register",
    "code_challenge_methods_supported": ["S256"],
    "scopes_supported": ["read:jira", "offline_access"],
    "resource": "https://mcp.example.com/v2/mcp",
}


async def _verified_dcr_server(admin_client, db) -> str:
    server_id = await _create_server(admin_client, is_global=True)
    from vendor.services.mcp_service import get_mcp_server

    server_row = await get_mcp_server(db, server_id=server_id)
    server_row.auth_type = "oauth2"
    server_row.auth_config = {"auth_type": "oauth2", "transport": "streamable_http", "oauth": dict(_DCR_OAUTH)}
    server_row.status = "VERIFIED"
    await db.commit()
    return server_id


def _patch_registration(monkeypatch) -> list[dict]:
    import json

    import httpx

    registrations: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == _DCR_OAUTH["registration_endpoint"]
        registrations.append(json.loads(request.content))
        return httpx.Response(201, json={"client_id": f"DCR{len(registrations)}"})

    monkeypatch.setattr(mcp_auth, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return registrations


@pytest.mark.asyncio
async def test_self_registering_server_signs_in_with_pkce_and_no_app_credentials(
    tenant_client, admin_client, anon_client, monkeypatch, db, tenant
):
    """No one types a client ID: the first sign-in registers a public client,
    the authorize URL carries a PKCE S256 challenge and the RFC 8707 resource,
    and the code is redeemed with the matching verifier and no secret."""
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlsplit

    server_id = await _verified_dcr_server(admin_client, db)
    registrations = _patch_registration(monkeypatch)

    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert res.status_code == 200, res.text
    query = parse_qs(urlsplit(res.json()["authorization_url"]).query)
    assert query["client_id"] == ["DCR1"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["resource"] == [_DCR_OAUTH["resource"]]
    assert query["scope"] == ["read:jira offline_access"]
    assert registrations[0]["redirect_uris"][0].endswith("/mcp/oauth/callback")
    assert registrations[0]["token_endpoint_auth_method"] == "none"

    seen: dict = {}

    async def fake_exchange(oauth, credentials, *, code, redirect_uri, code_verifier=None):
        seen.update(credentials=credentials, code_verifier=code_verifier)
        return {"access_token": "ATL-ACCESS", "refresh_token": "ATL-REFRESH"}

    monkeypatch.setattr(mcp_auth, "exchange_authorization_code", fake_exchange)
    callback_res = await anon_client.get(
        f"{BASE}/mcp/oauth/callback", params={"code": "C1", "state": res.json()["state"]}
    )
    assert callback_res.status_code == 200, callback_res.text
    challenge = base64.urlsafe_b64encode(hashlib.sha256(seen["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert seen["credentials"] == {"client_id": "DCR1", "client_secret": ""}

    user_creds = await mcp_auth.load_server_credentials(db, server_id=server_id, tenant_id=tenant.id, user_id="tu_1")
    assert user_creds["refresh_token"] == "ATL-REFRESH"

    # The next person reuses the registered client.
    again = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert "client_id=DCR1" in again.json()["authorization_url"]
    assert len(registrations) == 1


@pytest.mark.asyncio
async def test_self_registering_server_registers_again_when_callback_url_moves(
    tenant_client, admin_client, monkeypatch, db
):
    """A new public URL (another ngrok address) can't use a client registered
    for the old redirect_uri, so the next sign-in registers a fresh one."""
    from apps.backend.config import get_backend_settings

    server_id = await _verified_dcr_server(admin_client, db)
    registrations = _patch_registration(monkeypatch)
    await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})

    monkeypatch.setattr(get_backend_settings(), "BACKEND_PUBLIC_URL", "https://moved.example.com")
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert "client_id=DCR2" in res.json()["authorization_url"]
    assert registrations[1]["redirect_uris"] == ["https://moved.example.com/api/v1/vendor/resources/mcp/oauth/callback"]


@pytest.mark.asyncio
async def test_admin_configured_app_is_not_replaced_by_registration(tenant_client, admin_client, monkeypatch, db):
    server_id = await _verified_dcr_server(admin_client, db)
    await mcp_auth.store_server_credentials(
        db, server_id=server_id, credentials={"oauth_client_id": "APPCID", "oauth_client_secret": "APPSEC"}, tenant_id=None
    )
    await db.commit()
    registrations = _patch_registration(monkeypatch)
    res = await tenant_client.post(f"{BASE}/mcp/{server_id}/oauth/authorize-as-user", json={})
    assert "client_id=APPCID" in res.json()["authorization_url"]
    assert registrations == []


@pytest.mark.asyncio
async def test_public_client_token_requests_send_client_id_verifier_and_resource(monkeypatch):
    import httpx
    from urllib.parse import parse_qs

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})

    monkeypatch.setattr(mcp_auth, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    creds = {"client_id": "DCR1", "client_secret": ""}
    await mcp_auth.exchange_authorization_code(
        _DCR_OAUTH, creds, code="C1", redirect_uri="https://b.example.com/cb", code_verifier="V" * 50
    )
    await mcp_auth._refresh_token_grant(_DCR_OAUTH, creds, "RT")

    for request in sent:
        form = parse_qs(request.content.decode())
        assert "authorization" not in request.headers
        assert form["client_id"] == ["DCR1"]
        assert form["resource"] == [_DCR_OAUTH["resource"]]
    assert parse_qs(sent[0].content.decode())["code_verifier"] == ["V" * 50]
