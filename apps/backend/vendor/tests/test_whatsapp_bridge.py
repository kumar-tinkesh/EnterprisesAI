"""Tests for per-user device-pairing bridges (WhatsApp): the manager's
lifecycle against a fake whatsapp-orchestrator (each user's bridge really
runs in its own container, which the orchestrator owns), the token that
guards each bridge's REST API, and the REST API's guard conditions.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from vendor.models import VendorMCPBridgeInstance
from vendor.services import mcp_auth
from vendor.services.whatsapp_bridge import manager as bridge_manager

BASE = "/api/v1/vendor/resources"


def _mcp_payload(name="whatsapp.mcp"):
    return {
        "name": name,
        "description": "WhatsApp MCP server.",
        "source_url": "https://github.com/lharries/whatsapp-mcp",
        "is_global": True,
    }


async def _create_device_pairing_server(admin_client, db, *, name="whatsapp.mcp") -> str:
    """Register a server and mark it VERIFIED + device_pairing, same shape
    as a real repo-analyzed WhatsApp entry (see the connection.py test
    fixtures' conventions for direct DB row edits post-creation)."""
    res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload(name))
    assert res.status_code == 201, res.text
    server_id = res.json()["id"]

    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=server_id)
    row.status = "VERIFIED"
    row.transport = "stdio"
    row.command = "python"
    row.args = ["whatsapp-mcp-server/main.py"]
    row.auth_config = {**(row.auth_config or {}), "auth_type": "device_pairing"}
    await db.commit()
    return server_id


class _FakeOrchestrator:
    """Stands in for the whatsapp-orchestrator service's HTTP API."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.bridge_status: dict = {"status": "starting", "qr": ""}
        self.fail: bool = False

    async def __call__(self, method, path, *, json=None, params=None):
        self.calls.append((method, path, json, params))
        if self.fail:
            raise bridge_manager.BridgeError("WhatsApp orchestrator unreachable: boom")
        if method == "GET":
            return dict(self.bridge_status)
        return {"status": "starting"}

    def started_tokens(self) -> list[str]:
        return [j["token"] for m, _p, j, _q in self.calls if m == "POST"]


@pytest.fixture
def orch(monkeypatch):
    fake = _FakeOrchestrator()
    monkeypatch.setattr(bridge_manager, "_orchestrator", fake)
    return fake


async def _row(db, server_id: str, user_id: str) -> VendorMCPBridgeInstance:
    db.expire_all()
    return (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == user_id,
            )
        )
    ).scalars().one()


async def _server(admin_client, db, name="whatsapp.mcp"):
    from vendor.services.mcp_service import get_mcp_server

    server_id = await _create_device_pairing_server(admin_client, db, name=name)
    return server_id, await get_mcp_server(db, server_id=server_id)


@pytest.mark.asyncio
async def test_start_asks_orchestrator_for_a_container_with_a_stored_token(admin_client, db, orch):
    server_id, server = await _server(admin_client, db)

    result = await bridge_manager.start_bridge(db, server=server, user_id="tu_1", tenant_id="tenant_test_01")

    assert result == {"status": "starting"}
    row = await _row(db, server_id, "tu_1")
    (method, path, body, _), = orch.calls
    assert (method, path) == ("POST", f"/instances/{row.id}/start")
    token = body["token"]
    assert len(token) >= 32
    assert row.status == "starting"
    assert row.data_dir == bridge_manager.volume_name(row.id)
    # Stored encrypted, never in the clear.
    assert token not in (row.token_encrypted or "")
    assert bridge_manager._instance_token(row) == token


@pytest.mark.asyncio
async def test_status_goes_qr_then_connected_and_mirrors_credential(admin_client, db, orch):
    server_id, server = await _server(admin_client, db)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_2", tenant_id="tenant_test_01")

    orch.bridge_status = {"status": "waiting_for_scan", "qr": "2@abc,def"}
    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_2")
    assert status == {"status": "awaiting_qr", "qr": "2@abc,def"}
    assert await bridge_manager.get_mcp_env(db, server_id=server_id, user_id="tu_2") is None

    orch.bridge_status = {"status": "connected", "qr": ""}
    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_2")
    assert status == {"status": "connected"}
    creds = await mcp_auth.load_server_credentials(db, server_id=server_id, user_id="tu_2")
    assert creds.get("_bridge") == "connected"

    row = await _row(db, server_id, "tu_2")
    env = await bridge_manager.get_mcp_env(db, server_id=server_id, user_id="tu_2")
    assert env == {
        "WHATSAPP_API_BASE_URL": f"http://eai-wa-bridge-{row.id}:8080/api",
        "WHATSAPP_BRIDGE_TOKEN": orch.started_tokens()[0],
        "WHATSAPP_DEFAULT_COUNTRY_CODE": "91",
    }


@pytest.mark.asyncio
async def test_each_user_gets_their_own_container_and_token(admin_client, db, orch):
    server_id, server = await _server(admin_client, db)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_a", tenant_id="tenant_test_01")
    await bridge_manager.start_bridge(db, server=server, user_id="tu_b", tenant_id="tenant_test_01")

    paths = [p for m, p, _j, _q in orch.calls if m == "POST"]
    tokens = orch.started_tokens()
    assert len(set(paths)) == 2
    assert len(set(tokens)) == 2


@pytest.mark.asyncio
async def test_qr_timeout_marks_error(admin_client, db, orch):
    server_id, server = await _server(admin_client, db)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_3", tenant_id="tenant_test_01")

    orch.bridge_status = {"status": "timeout", "qr": ""}
    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_3")
    assert status["status"] == "error"
    assert "Timed out" in status["error"]


@pytest.mark.asyncio
async def test_disconnect_keeps_session_and_token_forget_rotates_them(admin_client, db, orch):
    server_id, server = await _server(admin_client, db)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_4", tenant_id="tenant_test_01")
    orch.bridge_status = {"status": "connected", "qr": ""}
    await bridge_manager.get_status(db, server_id=server_id, user_id="tu_4")
    first_token = orch.started_tokens()[0]

    await bridge_manager.stop_bridge(db, server_id=server_id, user_id="tu_4", wipe=False)
    assert orch.calls[-1][3] == {"purge": "false"}
    assert (await _row(db, server_id, "tu_4")).status == "not_connected"
    assert await mcp_auth.load_server_credentials(db, server_id=server_id, user_id="tu_4") == {}
    assert await bridge_manager.get_status(db, server_id=server_id, user_id="tu_4") == {"status": "not_connected"}

    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_4", tenant_id="tenant_test_01")
    assert orch.started_tokens()[-1] == first_token  # same container env, no new QR

    await bridge_manager.stop_bridge(db, server_id=server_id, user_id="tu_4", wipe=True)
    assert orch.calls[-1][3] == {"purge": "true"}
    server = await get_mcp_server(db, server_id=server_id)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_4", tenant_id="tenant_test_01")
    assert orch.started_tokens()[-1] != first_token


@pytest.mark.asyncio
async def test_connect_as_user_reports_orchestrator_failure(admin_client, tenant_client, db, orch):
    server_id = await _create_device_pairing_server(admin_client, db, name="wa-down")
    orch.fail = True
    resp = await tenant_client.post(f"{BASE}/mcp/{server_id}/bridge/connect-as-user")
    assert resp.status_code == 502
    assert "orchestrator" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_user_runtime_points_at_their_own_container(admin_client, db, orch):
    import sys

    from vendor.services.mcp_service import build_runtime_config

    server_id, server = await _server(admin_client, db)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_rt", tenant_id=None)
    orch.bridge_status = {"status": "connected", "qr": ""}
    await bridge_manager.get_status(db, server_id=server_id, user_id="tu_rt")

    config = await build_runtime_config(db, server=server, user_id="tu_rt", tenant_id=None)
    row = await _row(db, server_id, "tu_rt")
    assert config["command"] == sys.executable
    assert config["env_vars"]["WHATSAPP_API_BASE_URL"] == f"http://eai-wa-bridge-{row.id}:8080/api"
    assert config["env_vars"]["WHATSAPP_BRIDGE_TOKEN"] == orch.started_tokens()[0]


# ── REST API guard conditions (no container started at all) ─────────────


@pytest.mark.asyncio
async def test_bridge_connect_rejects_non_device_pairing_server(admin_client, tenant_client):
    res = await admin_client.post(f"{BASE}/mcp", json={
        "name": "not-whatsapp", "description": "d",
        "source_url": "https://mcp.example.com/x", "is_global": True,
    })
    server_id = res.json()["id"]
    resp = await tenant_client.post(f"{BASE}/mcp/{server_id}/bridge/connect-as-user")
    assert resp.status_code == 400
    assert "device pairing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_bridge_connect_requires_verified_server(admin_client, tenant_client, db):
    res = await admin_client.post(f"{BASE}/mcp", json=_mcp_payload("wa-unverified"))
    server_id = res.json()["id"]
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=server_id)
    row.auth_config = {**(row.auth_config or {}), "auth_type": "device_pairing"}
    await db.commit()
    # device_pairing but never verified/connected -> 409, not 400.
    resp = await tenant_client.post(f"{BASE}/mcp/{server_id}/bridge/connect-as-user")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_bridge_connect_forbidden_for_invisible_server(admin_client, solo_client, db):
    server_id = await _create_device_pairing_server(admin_client, db, name="wa-restricted")
    from vendor.services.mcp_service import get_mcp_server

    row = await get_mcp_server(db, server_id=server_id)
    row.is_global = False
    await db.commit()

    resp = await solo_client.post(f"{BASE}/mcp/{server_id}/bridge/connect-as-user")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_as_user_not_connected_when_never_started(admin_client, tenant_client, db):
    server_id = await _create_device_pairing_server(admin_client, db, name="wa-fresh")
    resp = await tenant_client.get(f"{BASE}/mcp/{server_id}/bridge/status-as-user")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_admin_test_runs_vendored_server_without_bridge(admin_client, db, monkeypatch):
    """The vendor admin's test must not spawn the raw upstream clone: it runs
    our vendored server with the backend's interpreter, needs no bridge, and
    leaves the server VERIFIED as device_pairing so users can pair."""
    import sys

    import vendor.services.mcp_service as ms
    from apps.backend.config import get_backend_settings
    from vendor.services.mcp_service import get_mcp_server

    server_id = await _create_device_pairing_server(admin_client, db)
    server = await get_mcp_server(db, server_id=server_id)
    server.status = "UNCONNECTED"
    captured: dict = {}

    async def _fake_connect(self, config):
        captured.update(config)
        return {"transport": "stdio", "bound_tools": ["send_message"],
                "tools": [{"name": "send_message"}], "auth_type": "none"}

    monkeypatch.setattr("vendor.services.mcp_service.MCPClient.connect", _fake_connect)

    res = await ms.test_mcp_connection(db, server=server)

    assert captured["command"] == sys.executable
    assert captured["args"] == [get_backend_settings().WHATSAPP_MCP_SERVER_SCRIPT]
    assert captured["source_repo_url"] is None
    assert captured["env_vars"] == {}
    assert res["status"] == "VERIFIED"
    assert server.auth_type == "device_pairing"


@pytest.mark.asyncio
async def test_user_runtime_without_live_bridge_is_refused(admin_client, db):
    from vendor.services.mcp_service import build_runtime_config, get_mcp_server

    server_id = await _create_device_pairing_server(admin_client, db)
    server = await get_mcp_server(db, server_id=server_id)
    with pytest.raises(mcp_auth.McpAuthError, match="isn't connected yet"):
        await build_runtime_config(db, server=server, user_id="tu_nobridge", tenant_id=None)


# ── A bridge whose container is gone isn't "connected" (drop_dead_bridges) ──


async def _connected(admin_client, db, orch, user_id):
    server_id, server = await _server(admin_client, db, name=f"wa-{user_id}")
    await bridge_manager.start_bridge(db, server=server, user_id=user_id, tenant_id="tenant_test_01")
    orch.bridge_status = {"status": "connected", "qr": ""}
    await bridge_manager.get_status(db, server_id=server_id, user_id=user_id)
    row = await _row(db, server_id, user_id)
    bridge_manager._live_checked.pop(row.id, None)  # as if the last look was long ago
    return server_id


@pytest.mark.asyncio
async def test_a_removed_container_stops_counting_as_connected(admin_client, db, orch):
    server_id = await _connected(admin_client, db, orch, "tu_gone")
    orch.bridge_status = {"status": "not_started", "qr": ""}  # the orchestrator found no container

    assert await mcp_auth.has_user_credential(db, server_id=server_id, user_id="tu_gone") is False
    await db.commit()
    row = await _row(db, server_id, "tu_gone")
    assert row.status == "not_connected" and "Connect again" in row.last_error
    assert await bridge_manager.get_mcp_env(db, server_id=server_id, user_id="tu_gone") is None


@pytest.mark.asyncio
async def test_a_live_booting_or_unreachable_bridge_is_left_connected(admin_client, db, orch):
    server_id = await _connected(admin_client, db, orch, "tu_live")

    assert await mcp_auth.has_user_credential(db, server_id=server_id, user_id="tu_live") is True
    gets = [c for c in orch.calls if c[0] == "GET"]
    # Seen connected just now: the next question doesn't ask the orchestrator again.
    assert await mcp_auth.has_user_credential(db, server_id=server_id, user_id="tu_live") is True
    assert [c for c in orch.calls if c[0] == "GET"] == gets

    row = await _row(db, server_id, "tu_live")
    for status in ("starting", None):  # still booting; orchestrator down
        bridge_manager._live_checked.pop(row.id, None)
        orch.fail = status is None
        orch.bridge_status = {"status": status or "x", "qr": ""}
        assert await mcp_auth.has_user_credential(db, server_id=server_id, user_id="tu_live") is True
    assert (await _row(db, server_id, "tu_live")).status == "connected"


@pytest.mark.asyncio
async def test_the_catalog_shows_a_gone_bridge_as_not_connected(admin_client, tenant_client, tenant_user, db, orch):
    server_id = await _connected(admin_client, db, orch, tenant_user.id)
    orch.bridge_status = {"status": "exited", "qr": ""}

    r = await tenant_client.get(f"{BASE}/catalog")
    assert next(s for s in r.json()["servers"] if s["id"] == server_id)["connected"] is False
    row = await _row(db, server_id, tenant_user.id)
    assert row.status == "error" and "exited" in row.last_error


def _vendored_whatsapp(monkeypatch, country_code):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    monkeypatch.setenv("WHATSAPP_DEFAULT_COUNTRY_CODE", country_code)
    monkeypatch.setitem(sys.modules, "audio", types.ModuleType("audio"))
    path = Path(bridge_manager.__file__).parent / "vendor_src" / "server" / "whatsapp.py"
    spec = importlib.util.spec_from_file_location("vendored_whatsapp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_numbers_are_sent_with_their_country_code(monkeypatch):
    wa = _vendored_whatsapp(monkeypatch, "91")
    for written in ("8789977380", "+91 87899-77380", "08789977380", "918789977380", "0091 8789977380"):
        assert wa.normalize_recipient(written) == ("918789977380", None), written
    assert wa.normalize_recipient("+1 (415) 555-0100") == ("14155550100", None)
    assert wa.normalize_recipient("120363@g.us") == ("120363@g.us", None)
    for bad in ("", "123", "call me", "4155550100x"):
        assert wa.normalize_recipient(bad)[0] is None, bad

    # A bad number never reaches the bridge.
    assert wa.send_message("123", "hi")[0] is False


def test_without_a_default_a_bare_number_is_refused_clearly(monkeypatch):
    wa = _vendored_whatsapp(monkeypatch, "")
    to, problem = wa.normalize_recipient("8789977380")
    assert to is None and "country code" in problem and "918789977380" in problem
