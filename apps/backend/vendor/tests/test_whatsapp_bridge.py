"""Tests for the native per-user device-pairing bridge (WhatsApp) — process
lifecycle state machine (with a fake subprocess standing in for the real
compiled Go binary) and the REST API's guard conditions.

The fake subprocess replays scripted stdout lines through the *real*
``===EAI_QR_START===``/``===EAI_QR_END===`` delimiter protocol and the real
"Connected to WhatsApp!" signal (see vendor_src/README.md), so these tests
exercise the actual parsing/state-machine logic in
``vendor.services.whatsapp_bridge.manager`` — only the OS process itself is
faked.
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

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


class _FakeStdout:
    """Stands in for a real subprocess's stdout pipe. Critically, each
    ``readline()`` actually yields control back to the event loop first
    (``asyncio.sleep(0)``) — a real pipe read always does this implicitly
    (bytes arrive over time); without it, the background reader task
    (``_watch_process``, a separate asyncio Task) races ahead of and
    interleaves with whatever coroutine is concurrently awaiting
    ``start_bridge()`` in the same test, which is a timing artifact of the
    fake process having zero I/O latency — not a bug in the manager, and
    not representative of the real subprocess it stands in for."""

    def __init__(self, lines: list[bytes], *, hang_at_eof: bool = False):
        self._lines = list(lines)
        self._hang_at_eof = hang_at_eof

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if self._lines:
            return self._lines.pop(0)
        if self._hang_at_eof:
            # A real bridge process, once connected, keeps running
            # indefinitely serving its REST API — it does not exit just
            # because it printed a status line. Model that by blocking
            # forever here instead of signalling EOF, so the reader task
            # (and this instance's registry entry) stays alive exactly
            # like the real, still-running process it stands in for.
            await asyncio.Event().wait()
        return b""


class _FakeProcess:
    def __init__(self, lines: list[str], exit_code: int = 0, *, hang_at_eof: bool = False):
        self.stdout = _FakeStdout([(line + "\n").encode() for line in lines], hang_at_eof=hang_at_eof)
        self.returncode: int | None = None
        self._exit_code = exit_code
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        self.returncode = self._exit_code
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = self._exit_code

    def kill(self) -> None:
        self.killed = True
        self.returncode = self._exit_code


def _qr_success_lines() -> list[str]:
    return [
        "Starting WhatsApp client...",
        "Scan this QR code with your WhatsApp app:",
        "===EAI_QR_START===",
        "█████ FAKE QR BLOCK █████",
        "█████████████████████████",
        "===EAI_QR_END===",
        "Successfully connected and authenticated!",
        "Connected to WhatsApp!",
    ]


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


async def _wait_until_async(predicate, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


@pytest.fixture(autouse=True)
def _fake_binary_exists(monkeypatch, tmp_path):
    """start_bridge refuses to run if the configured binary path doesn't
    exist on disk — true in the test environment (no real compiled bridge).
    Stub the check; the fake process below stands in for the real one.
    Also redirect the data-dir root under pytest's tmp_path — the real
    default (/data/...) isn't writable outside the deployed container.

    Deliberately does *not* touch ``bridge_manager.SessionLocal`` — it
    already resolves to the same test database as the ``db``/``admin_client``
    fixtures (conftest.py sets ``DATABASE_URL`` before ``src.db.session`` is
    first imported), and each concurrent caller (the background stdout
    watcher vs. ``start_bridge``'s own inline persist call) needs its *own*
    independent session, exactly like production — sharing one across
    concurrent coroutines corrupts both (AsyncSession isn't safe for
    concurrent use)."""
    monkeypatch.setattr(bridge_manager.os.path, "isfile", lambda _path: True)

    def _fake_instance_data_dir(server_id: str, user_id: str) -> str:
        return str(tmp_path / "whatsapp_bridges" / server_id / user_id)

    monkeypatch.setattr(bridge_manager, "_instance_data_dir", _fake_instance_data_dir)


@pytest.fixture(autouse=True)
async def _cleanup_registry():
    yield
    # Don't leak a "running" fake process/task across tests if one crashed
    # mid-assertion — and *wait* for the cancellation to actually land, or
    # a straggler task can still be mid-flight (e.g. about to open its own
    # DB session) when the *next* test starts, racing with and corrupting
    # that test's own session use.
    tasks = []
    for key in list(bridge_manager._registry.keys()):
        running = bridge_manager._registry.pop(key, None)
        if running and running.reader_task:
            running.reader_task.cancel()
            tasks.append(running.reader_task)
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_bridge_reaches_awaiting_qr_then_connected(admin_client, db, monkeypatch):
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    async def fake_spawn(*_args, **_kwargs):
        return _FakeProcess(_qr_success_lines(), hang_at_eof=True)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)

    result = await bridge_manager.start_bridge(db, server=server, user_id="tu_1", tenant_id="tenant_test_01")
    # The immediate return is a snapshot only — with a real subprocess
    # there's always some latency before its first output, so this is
    # reliably "starting"; the fake process here has near-zero latency, so
    # it can legitimately have already progressed by the time we return.
    assert result["status"] in ("starting", "awaiting_qr", "connected")

    await _wait_until(
        lambda: bridge_manager._registry[(server_id, "tu_1")].status == "connected"
    )

    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_1")
    assert status["status"] == "connected"

    # The catalog-visibility system (VendorMCPCredential), not just the
    # bridge's own table, must also reflect the connection. The in-memory
    # status flips *before* that DB write (a real caller's own "connected"
    # observation and this mirroring write aren't atomic), so poll rather
    # than assume it's already landed the instant get_status() says so.
    async def _creds_mirrored() -> bool:
        creds = await mcp_auth.load_server_credentials(db, server_id=server_id, user_id="tu_1")
        return creds.get("_bridge") == "connected"

    await _wait_until_async(_creds_mirrored)


@pytest.mark.asyncio
async def test_concurrent_users_get_distinct_ports(admin_client, db, monkeypatch):
    """Regression test for a real bug found in live testing: the real
    bridge binary doesn't bind its REST port at startup — only much later,
    after a successful pairing — so an OS-level "is this port free right
    now" check alone can't detect a collision between two users starting
    around the same time; both can pass that check for the *same* port
    before either has actually bound it. Port allocation must be based on
    this module's own bookkeeping (registry + DB), not just the OS."""
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    async def fake_spawn(*_args, **_kwargs):
        # Never reaches "Connected to WhatsApp!" — mirrors the real binary
        # never having bound its port at this stage either.
        return _FakeProcess(["Scan this QR code with your WhatsApp app:"], hang_at_eof=True)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)

    await bridge_manager.start_bridge(db, server=server, user_id="tu_race_a", tenant_id="tenant_test_01")
    await bridge_manager.start_bridge(db, server=server, user_id="tu_race_b", tenant_id="tenant_test_01")

    port_a = bridge_manager._registry[(server_id, "tu_race_a")].port
    port_b = bridge_manager._registry[(server_id, "tu_race_b")].port
    assert port_a != port_b, f"both users got the same port: {port_a}"


@pytest.mark.asyncio
async def test_qr_text_captured_between_delimiters(admin_client, db, monkeypatch):
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    lines = [
        "Scan this QR code with your WhatsApp app:",
        "===EAI_QR_START===",
        "LINE1",
        "LINE2",
        "===EAI_QR_END===",
    ]

    async def fake_spawn(*_args, **_kwargs):
        # A real bridge doesn't exit just because it printed the QR — it
        # waits (up to ~3 minutes) for the scan. Model that so the registry
        # entry doesn't disappear out from under this test.
        return _FakeProcess(lines, hang_at_eof=True)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)

    await bridge_manager.start_bridge(db, server=server, user_id="tu_2", tenant_id="tenant_test_01")
    await _wait_until(
        lambda: bridge_manager._registry.get((server_id, "tu_2"))
        and bridge_manager._registry[(server_id, "tu_2")].status == "awaiting_qr"
    )
    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_2")
    assert status["status"] == "awaiting_qr"
    assert status["qr"] == "LINE1\nLINE2"


@pytest.mark.asyncio
async def test_qr_scan_timeout_marks_error(admin_client, db, monkeypatch):
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    lines = [
        "Scan this QR code with your WhatsApp app:",
        "===EAI_QR_START===",
        "X",
        "===EAI_QR_END===",
        "Timeout waiting for QR code scan",
    ]

    async def fake_spawn(*_args, **_kwargs):
        return _FakeProcess(lines, exit_code=1)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)

    await bridge_manager.start_bridge(db, server=server, user_id="tu_3", tenant_id="tenant_test_01")
    # Unlike "connected", a real bridge process genuinely exits after this
    # log line (see vendor_src/bridge/main.go) — so the in-memory registry
    # entry is expected to disappear once the reader task's finally block
    # runs. Check the *durable* (DB-backed) status instead of the transient
    # in-memory one, matching how a real caller (the frontend polling
    # status-as-user) would observe the outcome after the process is gone.
    async def _is_error() -> bool:
        status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_3")
        return status["status"] == "error"

    await _wait_until_async(_is_error)


@pytest.mark.asyncio
async def test_stop_bridge_keeps_session_by_default(admin_client, db, monkeypatch, tmp_path):
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    async def fake_spawn(*_args, **_kwargs):
        return _FakeProcess(_qr_success_lines(), hang_at_eof=True)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_4", tenant_id="tenant_test_01")
    await _wait_until(
        lambda: bridge_manager._registry[(server_id, "tu_4")].status == "connected"
    )

    await bridge_manager.stop_bridge(db, server_id=server_id, user_id="tu_4", wipe=False)

    assert (server_id, "tu_4") not in bridge_manager._registry
    status = await bridge_manager.get_status(db, server_id=server_id, user_id="tu_4")
    assert status["status"] == "not_connected"
    # catalog-visibility credential row removed on disconnect too
    creds = await mcp_auth.load_server_credentials(db, server_id=server_id, user_id="tu_4")
    assert creds == {}

    from vendor.models import VendorMCPBridgeInstance
    from sqlalchemy import select

    row = (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == "tu_4",
            )
        )
    ).scalars().first()
    assert row is not None
    assert row.status == "not_connected"


@pytest.mark.asyncio
async def test_forget_bridge_wipes_data_dir(admin_client, db, monkeypatch, tmp_path):
    server_id = await _create_device_pairing_server(admin_client, db)
    from vendor.services.mcp_service import get_mcp_server

    server = await get_mcp_server(db, server_id=server_id)

    async def fake_spawn(*_args, **_kwargs):
        return _FakeProcess(_qr_success_lines(), hang_at_eof=True)

    monkeypatch.setattr(bridge_manager.asyncio, "create_subprocess_exec", fake_spawn)
    await bridge_manager.start_bridge(db, server=server, user_id="tu_5", tenant_id="tenant_test_01")
    await _wait_until(
        lambda: bridge_manager._registry[(server_id, "tu_5")].status == "connected"
    )

    from vendor.models import VendorMCPBridgeInstance
    from sqlalchemy import select

    row = (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == "tu_5",
            )
        )
    ).scalars().first()
    data_dir = row.data_dir
    import os

    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "marker"), "w") as f:
        f.write("x")

    await bridge_manager.stop_bridge(db, server_id=server_id, user_id="tu_5", wipe=True)
    assert not os.path.exists(data_dir)


# ── REST API guard conditions (no process spawned at all) ────────────────


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
