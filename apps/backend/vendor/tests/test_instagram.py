"""Instagram (thenavidm/instagram-mcp): the two fields it reads, IG_HOST from the token, a pasted token
checked and cleaned, and "Connect with Instagram" through Meta's Unified Login (no token pasted)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from vendor.services import mcp_auth
from vendor.services.mcp_auth import instagram

BASE = "/api/v1/vendor/resources"
REPO = "https://github.com/thenavidm/instagram-mcp"
FB_TOKEN = "EAAG" + "x" * 120
IG_TOKEN = "IGAA" + "y" * 120


@pytest.fixture
def captured(monkeypatch):
    seen: list[dict] = []

    async def _fake_connect(self, config):
        seen.append(dict(config))
        return {"transport": "stdio", "bound_tools": ["whoami"], "tools": [{"name": "whoami"}], "auth_type": "env"}

    monkeypatch.setattr("vendor.services.mcp_service.MCPClient.connect", _fake_connect)
    return seen


async def _server(admin_client, db, *, verified=True):
    """The row as repo analysis registered it before the profile existed (README's four names)."""
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "instagram", "description": "", "source_url": REPO, "is_global": True})
    assert res.status_code == 201, res.text
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=res.json()["id"])
    names = ["ACCESS_TOKEN", "CLIENT_SECRET", "IG_ACCESS_TOKEN", "IG_USER_ID"]
    fields = [{"name": n, "label": n, "type": "secret", "required": True, "location": "env"} for n in names]
    row.auth_config = {"auth_type": "env", "transport": "stdio", "credential_fields": fields, "required_env": names}
    row.auth_schema = {"fields": fields}
    row.auth_type = "env"
    row.env_vars = {**{n: "" for n in names}, "IG_HOST": "graph.facebook.com"}
    row.command, row.args, row.transport, row.source_type = "python", ["server.py"], "stdio", "github"
    row.status = "VERIFIED" if verified else row.status
    await db.commit()
    return row


# ── pasted tokens ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [FB_TOKEN, f' "{FB_TOKEN}" ', f"Bearer {FB_TOKEN}", FB_TOKEN[:50] + "\n" + FB_TOKEN[50:]])
def test_a_token_is_accepted_as_people_paste_it(raw):
    assert instagram.clean_token(raw) == FB_TOKEN


def test_the_host_follows_the_token():
    assert instagram.host_for(FB_TOKEN) == "graph.facebook.com"
    assert instagram.host_for(IG_TOKEN) == "graph.instagram.com"
    assert instagram.launch_credentials({"IG_ACCESS_TOKEN": IG_TOKEN, "IG_USER_ID": " 1784 1459 ", "meta_app_secret": "S"}) == {
        "IG_ACCESS_TOKEN": IG_TOKEN, "IG_HOST": "graph.instagram.com", "IG_USER_ID": "17841459",
    }


@pytest.mark.parametrize("bad, says", [
    ("", "Paste"), ("AQBx" + "z" * 200, "one-time code"), ("EAAshort", "too short"), (FB_TOKEN + "€", "characters"),
])
def test_what_isnt_a_token_says_why(bad, says):
    with pytest.raises(mcp_auth.McpAuthError, match=says):
        instagram.check_pasted({"IG_ACCESS_TOKEN": bad, "IG_USER_ID": "17841459296371900"})


async def test_the_profile_asks_for_two_fields_and_the_run_gets_the_host(admin_client, tenant_client, db, captured):
    row = await _server(admin_client, db)
    res = await tenant_client.post(
        f"{BASE}/mcp/{row.id}/connect-as-user",
        json={"credentials": {"IG_ACCESS_TOKEN": f'"{FB_TOKEN}"', "IG_USER_ID": "17841459296371900"}},
    )
    assert res.status_code == 200, res.text
    creds = captured[-1]["credentials"]
    assert creds == {"IG_ACCESS_TOKEN": FB_TOKEN, "IG_HOST": "graph.facebook.com", "IG_USER_ID": "17841459296371900"}
    assert "IG_HOST" not in (captured[-1].get("env_vars") or {})
    await db.refresh(row)
    assert row.auth_type == instagram.AUTH_TYPE and [f["name"] for f in row.auth_schema["fields"]] == ["IG_ACCESS_TOKEN", "IG_USER_ID"]

    # The catalog shows the two fields; no sign-in button until the admin sets up the Meta app.
    [entry] = [s for s in (await tenant_client.get(f"{BASE}/catalog")).json()["servers"] if s["id"] == row.id]
    assert entry["credential_fields"] == ["IG_ACCESS_TOKEN", "IG_USER_ID"] and entry["sign_in"] is None and entry["connected"]

    bad = await tenant_client.post(f"{BASE}/mcp/{row.id}/connect-as-user", json={"credentials": {"IG_ACCESS_TOKEN": "AQBcode" * 30, "IG_USER_ID": "1"}})
    assert bad.status_code >= 400 and "one-time code" in bad.text


# ── Connect with Instagram ───────────────────────────────────────────────────


async def test_connect_with_instagram_stores_the_users_own_token_and_account(
    admin_client, tenant_client, anon_client, db, tenant, monkeypatch
):
    row = await _server(admin_client, db)
    # Not set up: the button can't start.
    assert (await tenant_client.post(f"{BASE}/mcp/{row.id}/instagram/authorize")).status_code == 409

    res = await admin_client.put(f"{BASE}/mcp/{row.id}/instagram-sign-in", json={"app_id": "111", "app_secret": "SECRET", "config_id": "222"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["ready"] and out["redirect_uri"].endswith("/mcp/oauth/callback") and "SECRET" not in res.text
    # The secret can be left out on a later save; the admin's test token on the shared row stays.
    await mcp_auth.store_server_credentials(
        db, server_id=row.id, tenant_id=None,
        credentials={**await mcp_auth.load_server_credentials(db, server_id=row.id, tenant_id=None), "IG_ACCESS_TOKEN": FB_TOKEN},
    )
    await db.commit()
    assert (await admin_client.put(f"{BASE}/mcp/{row.id}/instagram-sign-in", json={"app_id": "111", "config_id": "333"})).status_code == 200
    shared = await mcp_auth.load_server_credentials(db, server_id=row.id, tenant_id=None)
    assert (shared["meta_app_secret"], shared["IG_ACCESS_TOKEN"]) == ("SECRET", FB_TOKEN)
    assert (await tenant_client.put(f"{BASE}/mcp/{row.id}/instagram-sign-in", json={"app_id": "1", "config_id": "2"})).status_code == 403

    [entry] = [s for s in (await tenant_client.get(f"{BASE}/catalog")).json()["servers"] if s["id"] == row.id]
    assert entry["sign_in"] == "instagram"

    start = await tenant_client.post(f"{BASE}/mcp/{row.id}/instagram/authorize")
    assert start.status_code == 200, start.text
    url = urlparse(start.json()["authorization_url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "www.facebook.com" and url.path.endswith("/dialog/oauth")
    assert (q["client_id"], q["config_id"], q["response_type"], q["override_default_response_type"]) == ("111", "333", "code", "true")
    assert "SECRET" not in start.text

    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append((request.url.path, params))
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "EAAUSER" + "u" * 80, "token_type": "bearer", "expires_in": 5184000})
        if request.url.path.endswith("/me/assigned_instagram_accounts"):
            return httpx.Response(200, json={"data": [{"id": "17841459296371900", "username": "anon_insta_8513"}]})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    monkeypatch.setattr(mcp_auth, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    done = await anon_client.get(f"{BASE}/mcp/oauth/callback", params={"code": "CODE1#_", "state": start.json()["state"]})
    assert done.status_code == 200, done.text
    assert "Connected as @anon_insta_8513" in done.text
    exchange = calls[0][1]
    assert (exchange["client_id"], exchange["client_secret"], exchange["code"]) == ("111", "SECRET", "CODE1")

    mine = await mcp_auth.load_server_credentials(db, server_id=row.id, tenant_id=tenant.id, user_id="tu_1")
    assert mine["IG_ACCESS_TOKEN"].startswith("EAAUSER") and mine["IG_USER_ID"] == "17841459296371900"
    assert mine["IG_USERNAME"] == "anon_insta_8513" and mine["IG_EXPIRES_AT"] and "meta_app_secret" not in mine
    [entry] = [s for s in (await tenant_client.get(f"{BASE}/catalog")).json()["servers"] if s["id"] == row.id]
    assert entry["connected"]


async def test_a_sign_in_without_an_instagram_account_says_what_to_do(admin_client, tenant_client, anon_client, db, monkeypatch):
    row = await _server(admin_client, db)
    await admin_client.put(f"{BASE}/mcp/{row.id}/instagram-sign-in", json={"app_id": "111", "app_secret": "S", "config_id": "222"})
    start = await tenant_client.post(f"{BASE}/mcp/{row.id}/instagram/authorize")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "EAAUSER" + "u" * 80})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(mcp_auth, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    done = await anon_client.get(f"{BASE}/mcp/oauth/callback", params={"code": "C", "state": start.json()["state"]})
    assert done.status_code == 400 and "professional" in done.text
