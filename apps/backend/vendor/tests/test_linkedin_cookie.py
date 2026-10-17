"""LinkedIn (stickerdaniel/linkedin-mcp-server) with each user's own li_at cookie: the server profile
that replaces the detected PROXY_* fields, the on-disk session the server reads, and the launch config
for the vendor admin's test, a user's connect and a user's run."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from vendor.services import mcp_auth
from vendor.services.mcp_auth import linkedin

BASE = "/api/v1/vendor/resources"
REPO = "https://github.com/stickerdaniel/linkedin-mcp-server"


@pytest.fixture(autouse=True)
def _tmp_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


@pytest.fixture
def captured(monkeypatch):
    seen: list[dict] = []

    async def _fake_connect(self, config):
        seen.append(dict(config))
        return {"transport": "stdio", "bound_tools": ["search_jobs"], "tools": [{"name": "search_jobs"}], "auth_type": "none"}

    monkeypatch.setattr("vendor.services.mcp_service.MCPClient.connect", _fake_connect)
    return seen


async def _legacy_server(admin_client, db):
    """A LinkedIn row as repo analysis registered it before the profile existed."""
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "linkdin", "description": "", "source_url": REPO, "is_global": True})
    assert res.status_code == 201, res.text
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=res.json()["id"])
    fields = [{"name": "PROXY_PASSWORD", "label": "Proxy Password", "type": "secret", "required": True, "location": "env"}]
    row.auth_config = {"auth_type": "env", "transport": "stdio", "credential_fields": fields, "required_env": []}
    row.auth_schema = {"fields": fields}
    row.auth_type = "env"
    row.env_vars = {"PROXY_PASSWORD": ""}
    row.command, row.args, row.transport, row.source_type = "python", ["server.py"], "stdio", "github"
    await db.commit()
    return row


@pytest.mark.parametrize("raw", ["AQEabc", ' "AQEabc" ', "li_at=AQEabc;", "LI_AT=AQEabc"])
def test_the_cookie_is_accepted_as_people_paste_it(raw):
    assert linkedin.normalize_li_at(raw) == "AQEabc"


def test_the_session_is_the_layout_the_server_reads():
    profile = linkedin.write_session("li_at=AQEabc")
    root = os.path.dirname(profile)
    assert os.path.isfile(os.path.join(profile, "First Run"))
    cookie = json.load(open(os.path.join(root, "cookies.json")))[0]
    assert (cookie["name"], cookie["value"], cookie["domain"]) == ("li_at", "AQEabc", ".linkedin.com")
    state = json.load(open(os.path.join(root, "source-state.json")))
    assert state["source_runtime_id"] != "linux-x86_64-container" and state["profile_path"] == profile
    assert oct(os.stat(os.path.join(root, "cookies.json")).st_mode & 0o777) == "0o600"
    # Same cookie, same root; another cookie, its own.
    assert linkedin.write_session("AQEabc") == profile
    assert linkedin.write_session("AQExyz") != profile
    with pytest.raises(mcp_auth.McpAuthError):
        linkedin.write_session("  ")


async def test_admin_test_needs_no_cookie_and_fixes_an_old_row(admin_client, db, captured):
    import vendor.services.mcp_service as ms

    server = await _legacy_server(admin_client, db)
    res = await ms.test_mcp_connection(db, server=server)

    (config,) = captured
    assert config["args"] == ["--claim-profile-root"]
    assert config["source_repo_url"] is None and config["working_directory"] is None
    assert config["env_vars"] == linkedin.ENV and config["credentials"] == {}
    assert "mcp-server-linkedin" in config["command"]
    assert res["status"] == "VERIFIED" and server.auth_type == linkedin.AUTH_TYPE
    # The admin is asked for nothing; each user for their li_at.
    assert server.auth_config["credential_fields"] == [] and server.env_vars == {}
    assert [f["name"] for f in server.auth_schema["fields"]] == ["LI_AT"]


async def test_a_new_linkedin_server_gets_the_profile_at_registration(admin_client, db):
    from vendor.services.mcp_service import get_mcp_server

    res = await admin_client.post(f"{BASE}/mcp", json={"name": "LinkedIn", "description": "", "source_url": REPO, "is_global": True})
    assert res.status_code == 201, res.text
    row = await get_mcp_server(db, server_id=res.json()["id"])
    assert row.auth_config["auth_type"] == linkedin.AUTH_TYPE and row.auth_type == linkedin.AUTH_TYPE


async def test_user_connect_and_run_use_their_own_cookie_as_a_session(admin_client, tenant_client, tenant_user, db, captured):
    import vendor.services.mcp_service as ms
    from vendor.services.mcp_service import build_runtime_config

    server = await _legacy_server(admin_client, db)
    await ms.test_mcp_connection(db, server=server)
    await db.commit()

    r = await tenant_client.get(f"{BASE}/catalog")
    entry = next(s for s in r.json()["servers"] if s["id"] == server.id)
    assert entry["credential_fields"] == ["LI_AT"] and entry["auth_type"] == linkedin.AUTH_TYPE

    # Connecting without the cookie is refused before anything starts.
    r = await tenant_client.post(f"{BASE}/mcp/{server.id}/connect-as-user", json={"credentials": {}})
    assert r.status_code == 400 and "li_at" in r.json()["detail"]

    r = await tenant_client.post(f"{BASE}/mcp/{server.id}/connect-as-user", json={"credentials": {"LI_AT": "li_at=AQEuser"}})
    assert r.status_code == 200, r.text
    connect = captured[-1]
    assert connect["args"][:2] == ["--claim-profile-root", "--user-data-dir"]
    assert "AQEuser" not in json.dumps(connect["env_vars"]) and connect["credentials"] == {}
    assert json.load(open(os.path.join(os.path.dirname(connect["args"][2]), "cookies.json")))[0]["value"] == "AQEuser"

    # A run reads the stored cookie: the same session.
    config = await build_runtime_config(db, server=server, user_id=tenant_user.id, tenant_id=tenant_user.tenant_id)
    assert config["args"] == connect["args"]
