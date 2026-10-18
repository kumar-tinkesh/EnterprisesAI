"""Servers that only run from their published package (vendor.services.known_servers): Wikidata."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BASE = "/api/v1/vendor/resources"
REPO = "https://github.com/cyanheads/wikidata-mcp-server"
PACKAGE_ARGS = ["-y", "@cyanheads/wikidata-mcp-server@0.1.19"]


@pytest.fixture
def captured(monkeypatch):
    seen: list[dict] = []

    async def _fake_connect(self, config):
        seen.append(dict(config))
        return {"transport": "stdio", "bound_tools": ["wikidata_search_entities"],
                "tools": [{"name": "wikidata_search_entities"}], "auth_type": "none"}

    monkeypatch.setattr("vendor.services.mcp_service.MCPClient.connect", _fake_connect)
    return seen


async def _legacy_server(admin_client, db):
    """A Wikidata row as repo analysis registered it before the profile existed."""
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "wikidata", "description": "", "source_url": REPO, "is_global": True})
    assert res.status_code == 201, res.text
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=res.json()["id"])
    fields = [{"name": "MCP_AUTH_SECRET_KEY", "label": "Mcp Auth Secret Key", "type": "secret", "required": True, "location": "env"}]
    row.auth_config = {"auth_type": "env", "transport": "stdio", "credential_fields": fields, "required_env": []}
    row.auth_schema, row.auth_type = {"fields": fields}, "env"
    row.env_vars = {"MCP_AUTH_SECRET_KEY": "", "OTEL_EXPORTER_OTLP_ENDPOINT": ""}
    row.command, row.args, row.transport, row.source_type = "node", ["dist/index.js"], "stdio", "github"
    await db.commit()
    return row


def _assert_profile(row):
    assert (row.command, row.args) == ("npx", PACKAGE_ARGS)
    assert row.env_vars == {"MCP_LOG_LEVEL": "warning"} and row.auth_type == "none"
    assert row.auth_config["credential_fields"] == [] and row.auth_schema == {"fields": []}


async def test_analysis_and_registration_use_the_package(admin_client, db):
    from vendor.services.mcp_service import get_mcp_server
    from vendor.services.repo_analyzer import analyze_repo

    preview = await analyze_repo(REPO)
    assert preview.required_env_vars == []
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "Wikidata", "description": "", "source_url": REPO, "is_global": True})
    assert res.status_code == 201, res.text
    _assert_profile(await get_mcp_server(db, server_id=res.json()["id"]))


async def test_connecting_an_old_row_runs_the_package_and_fixes_it(admin_client, db, captured):
    import vendor.services.mcp_service as ms

    server = await _legacy_server(admin_client, db)
    res = await ms.test_mcp_connection(db, server=server)

    (config,) = captured
    assert config["command"] == "npx" and config["args"] == PACKAGE_ARGS
    assert config["env_vars"] == {"MCP_LOG_LEVEL": "warning"}
    assert res["status"] == "VERIFIED"
    _assert_profile(server)


async def test_the_migration_fixes_existing_rows(admin_client, db):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    server = await _legacy_server(admin_client, db)
    path = Path(__file__).resolve().parents[3] / "auth" / "alembic" / "versions" / "e8f9a0b1c2d3_wikidata_from_npm_package.py"
    spec = importlib.util.spec_from_file_location("m_e8f9", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    await (await db.connection()).run_sync(run)
    await db.commit()
    await db.refresh(server)
    _assert_profile(server)


# ── Notion: NOTION_TOKEN only; an AUTH_TOKEN already saved still reaches the server ──

NOTION_REPO = "https://github.com/makenotion/notion-mcp-server"


async def _notion(admin_client, db):
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "notion", "description": "", "source_url": NOTION_REPO, "is_global": True})
    assert res.status_code == 201, res.text
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=res.json()["id"])
    fields = [{"name": n, "label": n, "type": "secret", "required": True, "location": "env"} for n in ("AUTH_TOKEN", "NOTION_TOKEN")]
    row.auth_config = {"auth_type": "env", "transport": "stdio", "credential_fields": fields, "required_env": []}
    row.auth_schema, row.auth_type, row.env_vars = {"fields": fields}, "env", {"AUTH_TOKEN": "", "NOTION_TOKEN": ""}
    row.command, row.args, row.transport, row.source_type, row.status = "npx", ["-y", "@notionhq/notion-mcp-server"], "stdio", "github", "VERIFIED"
    await db.commit()
    return row


async def test_notion_asks_for_notion_token_and_passes_an_old_auth_token_on(admin_client, tenant_client, tenant_user, db, captured):
    from vendor.services import mcp_auth
    from vendor.services.mcp_service import build_runtime_config

    server = await _notion(admin_client, db)
    # Connected before the fix, under the name the server never read.
    await mcp_auth.store_server_credentials(db, server_id=server.id, credentials={"AUTH_TOKEN": "ntn_abc"},
                                            tenant_id=tenant_user.tenant_id, user_id=tenant_user.id)
    await db.commit()

    config = await build_runtime_config(db, server=server, user_id=tenant_user.id, tenant_id=tenant_user.tenant_id)
    assert config["credentials"]["NOTION_TOKEN"] == "ntn_abc"
    assert config["command"] == "npx" and config["args"] == ["-y", "@notionhq/notion-mcp-server"]
    assert [f["name"] for f in server.auth_schema["fields"]] == ["NOTION_TOKEN"] and server.env_vars == {}

    await db.commit()
    r = await tenant_client.get(f"{BASE}/catalog")
    assert next(s for s in r.json()["servers"] if s["id"] == server.id)["credential_fields"] == ["NOTION_TOKEN"]


async def test_the_notion_migration_fixes_existing_rows(admin_client, db):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    server = await _notion(admin_client, db)
    path = Path(__file__).resolve().parents[3] / "auth" / "alembic" / "versions" / "f0a1b2c3d4e5_notion_token_field.py"
    spec = importlib.util.spec_from_file_location("m_f0a1", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    await (await db.connection()).run_sync(run)
    await db.commit()
    await db.refresh(server)
    assert [f["name"] for f in server.auth_config["credential_fields"]] == ["NOTION_TOKEN"] and server.env_vars == {}


# ── Gmail (jimsimoy/gmail-mcp): a Google sign-in, not a pasted refresh token ──

GMAIL_REPO = "https://github.com/jimsimoy/gmail-mcp"


async def _gmail(admin_client, db):
    """A Gmail row as repo analysis registered it: five env fields, two of them tool arguments."""
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "gmail", "description": "", "source_url": GMAIL_REPO, "is_global": True})
    assert res.status_code == 201, res.text
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=res.json()["id"])
    names = ("DRAFT_ID", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "THREAD_ID")
    fields = [{"name": n, "label": n, "type": "secret", "required": True, "location": "env"} for n in names]
    row.auth_config = {"auth_type": "env", "transport": "stdio", "credential_fields": fields, "required_env": []}
    row.auth_schema, row.auth_type, row.env_vars = {"fields": fields}, "env", {n: "" for n in names}
    row.command, row.args, row.transport, row.source_type = "uv", ["run", "gmail-mcp"], "stdio", "github"
    await db.commit()
    return row


def _assert_gmail(row):
    assert row.auth_type == "oauth2" and row.env_vars == {"GMAIL_ACCESS_LEVEL": "FULL"}
    assert [f["name"] for f in row.auth_config["credential_fields"]] == ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"]
    oauth = row.auth_config["oauth"]
    assert oauth["token_endpoint"] == "https://oauth2.googleapis.com/token"
    assert oauth["extra_authorize_params"] == {"access_type": "offline", "prompt": "consent"}
    assert "https://mail.google.com/" not in oauth["scopes_supported"]


async def test_gmail_signs_in_with_google_and_every_token_reaches_the_server(admin_client, tenant_client, tenant_user, db, captured, monkeypatch):
    import vendor.services.mcp_service as ms
    from vendor.services import mcp_auth, oauth_flow
    from vendor.services.mcp_service import build_runtime_config

    from vendor.services import known_servers

    server = await _gmail(admin_client, db)
    # The form now offers the OAuth client only, and the sign-in asks Google for offline access.
    known_servers.apply_profile(server)
    await db.commit()
    _assert_gmail(server)

    async def _exchange(oauth, credentials, *, code, redirect_uri):
        return {"access_token": f"at-{code}", "refresh_token": f"rt-{code}"}

    monkeypatch.setattr(mcp_auth, "exchange_authorization_code", _exchange)

    # The admin signs in once …
    r = await admin_client.post(f"{BASE}/mcp/{server.id}/oauth/authorize", json={"client_id": "cid.apps", "client_secret": "csec"})
    assert r.status_code == 200, r.text
    url = r.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?") and "access_type=offline" in url and "prompt=consent" in url
    assert "gmail.modify" in url
    srv, creds, tenant_id, user_id = await oauth_flow.complete_authorization(db, state=r.json()["state"], code="admin", extra_callback_params={})
    await mcp_auth.store_server_credentials(db, server_id=srv.id, credentials=creds, tenant_id=tenant_id, user_id=user_id)
    await db.commit()

    # … then tests with the fields the form shows; the refresh token from the sign-in is kept.
    res = await ms.test_mcp_connection(db, server=server, request_credentials={"GMAIL_CLIENT_ID": "cid.apps", "GMAIL_CLIENT_SECRET": "csec"})
    await db.commit()
    assert res["status"] == "VERIFIED" and server.auth_type == "oauth2"
    env = captured[-1]["credentials"]
    assert (env["GMAIL_CLIENT_ID"], env["GMAIL_CLIENT_SECRET"], env["GMAIL_REFRESH_TOKEN"]) == ("cid.apps", "csec", "rt-admin")
    shared = await mcp_auth.load_server_credentials(db, server_id=server.id)
    assert shared["refresh_token"] == "rt-admin" and shared["oauth_client_id"] == "cid.apps"

    # A person signs in with their own Google account — no client ID or secret asked of them.
    r = await tenant_client.post(f"{BASE}/mcp/{server.id}/oauth/authorize-as-user", json={})
    assert r.status_code == 200, r.text
    srv, creds, tenant_id, user_id = await oauth_flow.complete_authorization(db, state=r.json()["state"], code="user", extra_callback_params={})
    assert user_id == tenant_user.id and "oauth_client_secret" not in creds
    await mcp_auth.store_server_credentials(db, server_id=srv.id, credentials=creds, tenant_id=tenant_id, user_id=user_id)
    await db.commit()

    config = await build_runtime_config(db, server=server, user_id=tenant_user.id, tenant_id=tenant_user.tenant_id)
    assert config["credentials"]["GMAIL_REFRESH_TOKEN"] == "rt-user" and config["credentials"]["GMAIL_CLIENT_ID"] == "cid.apps"
    assert config["env_vars"] == {"GMAIL_ACCESS_LEVEL": "FULL"}


async def test_the_gmail_migration_fixes_existing_rows(admin_client, db):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    server = await _gmail(admin_client, db)
    path = Path(__file__).resolve().parents[3] / "auth" / "alembic" / "versions" / "6a1f3c9e2b7d_gmail_oauth.py"
    spec = importlib.util.spec_from_file_location("m_6a1f", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    await (await db.connection()).run_sync(run)
    await db.commit()
    await db.refresh(server)
    _assert_gmail(server)
