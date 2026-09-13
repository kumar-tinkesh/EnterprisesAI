"""Process lifecycle manager for native, per-user device-pairing bridges
(currently: WhatsApp — see ``vendor/services/whatsapp_bridge/vendor_src``).

Unlike every other auth type this system supports, a device-pairing
"credential" is not a secret that can be stored and reused across a
stateless HTTP request — it's a long-running, QR-authenticated background
process tied to one user's phone. This module owns that process's full
lifecycle: spawning it in an isolated directory + port per user, watching
its stdout for the QR block and the "connected" signal, persisting status
to ``VendorMCPBridgeInstance``, and tearing it down on disconnect.

The live OS process handle lives only in this module's in-memory
``_registry`` — it is *not* persisted, and does not survive a backend
restart. On restart, a fresh ``connect-as-user`` call re-spawns the process
pointed at the same ``data_dir``; if the bridge's own session inside that
directory is still valid it reconnects immediately with no new QR, exactly
mirroring how re-running the bridge locally behaves.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select

from apps.backend.config import get_backend_settings
from src.db.session import SessionLocal

from vendor.models import VendorMCPBridgeInstance, VendorMCPServer

logger = logging.getLogger("vendor.whatsapp_bridge")

# Lines bracketing the QR ASCII block — see vendor_src/README.md for why
# this delimiter was added to the vendored bridge instead of guessing at
# terminal-art format.
_QR_START = "===EAI_QR_START==="
_QR_END = "===EAI_QR_END==="
# Printed by the bridge immediately before it starts serving its REST API —
# see vendor_src/bridge/main.go. The definitive "ready" signal.
_CONNECTED_SIGNAL = "Connected to WhatsApp!"
_QR_SCAN_TIMEOUT_SIGNAL = "Timeout waiting for QR code scan"

_LOG_TAIL_MAXLEN = 4000


class BridgeError(Exception):
    """Raised for a bridge lifecycle failure the caller should surface as a 4xx."""


@dataclass
class _RunningBridge:
    process: asyncio.subprocess.Process
    instance_id: str
    server_id: str
    user_id: str
    port: int
    data_dir: str
    status: str = "starting"
    qr_text: Optional[str] = None
    log_tail: str = ""
    started_at: float = field(default_factory=time.monotonic)
    last_connected_at: Optional[float] = None
    reader_task: Optional[asyncio.Task] = None


# In-memory registry — same convention as mcp_auth.storage's token cache
# and oauth_flow's pending-authorization store: single-process, fine for
# this deployment's single backend instance (see vendor_src/README.md's
# "Scaling" caveat for the multi-replica limitation).
_registry: dict[tuple[str, str], _RunningBridge] = {}
_registry_lock = asyncio.Lock()


def _instance_data_dir(server_id: str, user_id: str) -> str:
    settings = get_backend_settings()
    return os.path.join(settings.WHATSAPP_BRIDGE_DATA_ROOT, server_id, user_id)


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


async def _allocate_port(db, preferred: int, *, exclude_instance_id: str) -> int:
    """Prefer the instance's previously-used port (stable across restarts,
    friendlier for debugging); fall back to scanning the configured range.

    Checking only "is the OS listening on this port right now"
    (``_port_is_free``) is *not* enough on its own: the real bridge binary
    doesn't bind its REST port at startup — it only does so much later,
    after a successful WhatsApp pairing (see vendor_src/bridge/main.go).
    Two users connecting around the same time can both pass an OS-level
    free-port check for the same port before either process has actually
    bound anything, and both then get handed the same port. The
    authoritative source of "is this port already spoken for" is instead
    our own bookkeeping — every other instance's ``port`` in the DB, plus
    every port already claimed in the live in-memory registry (a instance
    that's running but hasn't persisted yet). ``_port_is_free`` is kept as
    a secondary sanity check, not the primary one.
    """
    settings = get_backend_settings()
    claimed = {r.port for r in _registry.values() if r.port and r.instance_id != exclude_instance_id}
    rows = await db.execute(
        select(VendorMCPBridgeInstance.port).where(
            VendorMCPBridgeInstance.port != 0,
            VendorMCPBridgeInstance.id != exclude_instance_id,
        )
    )
    claimed.update(p for (p,) in rows.all())

    if preferred and preferred not in claimed and _port_is_free(preferred):
        return preferred
    for port in range(settings.WHATSAPP_BRIDGE_PORT_RANGE_START, settings.WHATSAPP_BRIDGE_PORT_RANGE_END):
        if port not in claimed and _port_is_free(port):
            return port
    raise BridgeError("No free port available in the configured bridge port range")


async def _get_or_create_instance(
    db, *, server_id: str, user_id: str, tenant_id: str | None
) -> VendorMCPBridgeInstance:
    row = (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == user_id,
            )
        )
    ).scalars().first()
    if row is not None:
        return row
    row = VendorMCPBridgeInstance(
        server_id=server_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status="not_connected",
        data_dir=_instance_data_dir(server_id, user_id),
        port=0,
    )
    db.add(row)
    await db.flush()
    return row


async def _persist_status(
    instance_id: str,
    *,
    status: str,
    port: int | None = None,
    last_error: str | None = None,
    connected: bool = False,
) -> None:
    """Write status from the background stdout-watcher / reaper, which run
    outside any request's injected session — opens its own short-lived one."""
    async with SessionLocal() as db:
        row = await db.get(VendorMCPBridgeInstance, instance_id)
        if row is None:
            return
        row.status = status
        if port is not None:
            row.port = port
        row.last_error = last_error
        if connected:
            row.last_connected_at = str(time.time())
            # The rest of the system (catalog "connected" gating, semantic
            # tool search visibility) reads VendorMCPCredential, not this
            # table — mirror the connected state there too (an empty row is
            # enough; there's no secret to store) so a device-pairing
            # server behaves like any other from the catalog's point of
            # view once its bridge is actually authenticated.
            from vendor.services import mcp_auth

            await mcp_auth.store_server_credentials(
                db,
                server_id=row.server_id,
                credentials={"_bridge": "connected"},
                tenant_id=row.tenant_id,
                user_id=row.user_id,
            )
        await db.commit()


def _status_dict(running: _RunningBridge) -> dict:
    out = {"status": running.status, "port": running.port}
    if running.status == "awaiting_qr":
        out["qr"] = running.qr_text
    if running.status == "error":
        out["error"] = running.log_tail[-500:]
    return out


async def _watch_process(running: _RunningBridge) -> None:
    """Background task: parse stdout for the QR block and the connected
    signal, persist transitions, and clean up on process exit."""
    in_qr = False
    qr_lines: list[str] = []
    assert running.process.stdout is not None
    try:
        while True:
            raw = await running.process.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip("\n")
            running.log_tail = (running.log_tail + line + "\n")[-_LOG_TAIL_MAXLEN:]

            if line.strip() == _QR_START:
                in_qr = True
                qr_lines = []
                continue
            if line.strip() == _QR_END:
                in_qr = False
                running.qr_text = "\n".join(qr_lines)
                running.status = "awaiting_qr"
                await _persist_status(running.instance_id, status="awaiting_qr", port=running.port)
                continue
            if in_qr:
                qr_lines.append(line)
                continue
            if _CONNECTED_SIGNAL in line:
                running.status = "connected"
                running.qr_text = None
                running.last_connected_at = time.monotonic()
                await _persist_status(
                    running.instance_id, status="connected", port=running.port, connected=True
                )
                continue
            if _QR_SCAN_TIMEOUT_SIGNAL in line:
                running.status = "error"
                await _persist_status(
                    running.instance_id,
                    status="error",
                    port=running.port,
                    last_error="Timed out waiting for the QR code to be scanned. Click connect to try again.",
                )
                continue

        # stdout closed -> process exited.
        returncode = await running.process.wait()
        if running.status != "connected" or returncode != 0:
            err = running.log_tail[-500:] or f"Bridge process exited (code {returncode})"
            running.status = "error"
            await _persist_status(running.instance_id, status="error", port=running.port, last_error=err)
        else:
            # Was connected and the process died anyway (killed externally,
            # crashed, etc.) — leave the DB status as "connected" (the
            # session in data_dir is still valid) so the next connect-as-user
            # call reconnects instantly with no QR, but stop tracking it as
            # live in this process.
            pass
    except asyncio.CancelledError:
        raise
    finally:
        async with _registry_lock:
            key = (running.server_id, running.user_id)
            if _registry.get(key) is running:
                _registry.pop(key, None)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def start_bridge(
    db, *, server: VendorMCPServer, user_id: str, tenant_id: str | None
) -> dict:
    """Start (or resume) this user's bridge for ``server``. Returns a status
    dict — call ``get_status`` afterwards to poll for progress."""
    key = (server.id, user_id)
    async with _registry_lock:
        existing = _registry.get(key)
        if existing is not None and existing.process.returncode is None:
            return _status_dict(existing)

        instance = await _get_or_create_instance(
            db, server_id=server.id, user_id=user_id, tenant_id=tenant_id
        )
        await db.commit()

        data_dir = instance.data_dir or _instance_data_dir(server.id, user_id)
        os.makedirs(data_dir, exist_ok=True)
        port = await _allocate_port(db, instance.port, exclude_instance_id=instance.id)

        settings = get_backend_settings()
        binary = settings.WHATSAPP_BRIDGE_BINARY
        if not os.path.isfile(binary):
            raise BridgeError(
                f"WhatsApp bridge binary not found at {binary!r} — this deployment's "
                "image wasn't built with the bridge compiled in."
            )

        env = {**os.environ, "WHATSAPP_BRIDGE_PORT": str(port)}
        process = await asyncio.create_subprocess_exec(
            binary,
            cwd=data_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        running = _RunningBridge(
            process=process,
            instance_id=instance.id,
            server_id=server.id,
            user_id=user_id,
            port=port,
            data_dir=data_dir,
            status="starting",
        )
        running.reader_task = asyncio.create_task(_watch_process(running))
        _registry[key] = running

    await _persist_status(instance.id, status="starting", port=port)
    return _status_dict(running)


async def get_status(db, *, server_id: str, user_id: str) -> dict:
    """Live status if this process has the bridge registered in memory,
    else the last known status from the DB (with transient states that
    require a live process — 'starting'/'awaiting_qr' — normalized to
    'not_connected' since they can't mean anything without one)."""
    running = _registry.get((server_id, user_id))
    if running is not None:
        return _status_dict(running)

    row = (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == user_id,
            )
        )
    ).scalars().first()
    if row is None:
        return {"status": "not_connected"}
    status = row.status
    if status in ("starting", "awaiting_qr", "connected"):
        # None of these mean anything without a live process in *this*
        # process's registry (most likely: backend restarted since). The
        # underlying session in data_dir is probably still intact though —
        # calling start_bridge again reconnects near-instantly with no new
        # QR rather than requiring one, so this is reported the same as
        # never-connected rather than as an error.
        status = "not_connected"
    return {"status": status, "error": row.last_error}


def get_running_endpoint(server_id: str, user_id: str) -> tuple[int, str] | None:
    """(port, data_dir) for a *live* instance only, or None — used by
    mcp_service to point the stdio MCP server at the right bridge. Deliberately
    public (not reaching into ``_registry`` from other modules) so this
    module stays the single source of truth for what "live" means."""
    running = _registry.get((server_id, user_id))
    if running is None:
        return None
    return running.port, running.data_dir


async def stop_bridge(db, *, server_id: str, user_id: str, wipe: bool) -> None:
    """Stop this user's bridge process. ``wipe=False`` keeps the session
    (a future connect reconnects with no QR); ``wipe=True`` deletes the
    data_dir too ("forget this device" — always requires a fresh QR next
    time)."""
    key = (server_id, user_id)
    async with _registry_lock:
        running = _registry.pop(key, None)
    if running is not None:
        if running.reader_task is not None:
            running.reader_task.cancel()
        await _terminate(running.process)

    row = (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == user_id,
            )
        )
    ).scalars().first()
    if row is None:
        return
    if wipe:
        shutil.rmtree(row.data_dir, ignore_errors=True)
        row.port = 0
    row.status = "not_connected"
    row.last_error = None

    from vendor.services import mcp_auth

    await mcp_auth.delete_user_credential(db, server_id=server_id, user_id=user_id)
    await db.commit()


async def reap_idle_bridges() -> None:
    """Periodic background task (see apps/backend/main.py's lifespan):
    stop any bridge that's been connected but idle beyond the configured
    timeout. Never touches one still in 'starting'/'awaiting_qr' — the
    bridge's own internal 3-minute QR timeout handles that case by exiting
    on its own, which _watch_process already detects."""
    settings = get_backend_settings()
    now = time.monotonic()
    stale: list[tuple[str, str]] = []
    for key, running in list(_registry.items()):
        if running.status != "connected" or running.last_connected_at is None:
            continue
        if now - running.last_connected_at > settings.WHATSAPP_BRIDGE_IDLE_TIMEOUT_SECONDS:
            stale.append(key)
    for server_id, user_id in stale:
        logger.info("Reaping idle WhatsApp bridge for server=%s user=%s", server_id, user_id)
        async with SessionLocal() as db:
            await stop_bridge(db, server_id=server_id, user_id=user_id, wipe=False)


async def reaper_loop(interval_seconds: int = 300) -> None:
    """Run ``reap_idle_bridges`` forever on an interval — started as a
    background asyncio task at app startup, cancelled at shutdown."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await reap_idle_bridges()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WhatsApp bridge reaper loop iteration failed")


async def shutdown_all() -> None:
    """Stop every tracked bridge — called at app shutdown so we don't leak
    orphaned OS processes across a restart."""
    for (server_id, user_id) in list(_registry.keys()):
        async with SessionLocal() as db:
            await stop_bridge(db, server_id=server_id, user_id=user_id, wipe=False)
