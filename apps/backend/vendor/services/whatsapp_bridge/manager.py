"""Lifecycle of per-user device-pairing bridges (currently: WhatsApp — see
``vendor/services/whatsapp_bridge/vendor_src``).

A device-pairing "credential" is not a secret that can be stored and replayed
— it's a long-running, QR-authenticated WhatsApp Web session tied to one
user's phone. Each user's session runs in **its own container**
(``eai-wa-bridge-<instance id>``) with its own session volume, started and
stopped by the whatsapp-orchestrator service (``apps/whatsapp_orchestrator``),
the only service holding the docker socket. Nothing about a user's session
lives in the backend: it can't read another user's session files, and a
bridge survives backend restarts.

Every bridge's REST API requires a per-instance token (generated here, kept
Fernet-encrypted on ``VendorMCPBridgeInstance``) because the backend and
worker — which run arbitrary vendor-registered MCP servers — share the bridge
network. Only the user's own MCP server process is handed it (``get_mcp_env``).

State lives in the DB row, not in this process, so any backend or worker
process can build a user's MCP config.
"""
from __future__ import annotations

import logging
import secrets
import time

import httpx
from sqlalchemy import select

from apps.backend.config import get_backend_settings

from vendor.models import VendorMCPBridgeInstance, VendorMCPServer
from vendor.services.mcp_auth.crypto import decrypt_credentials, encrypt_credentials

logger = logging.getLogger("vendor.whatsapp_bridge")

BRIDGE_PORT = 8080

_QR_TIMEOUT_ERROR = "Timed out waiting for the QR code to be scanned. Click connect to try again."

# A bridge marked connected is re-checked against its container at most this often (see drop_dead_bridges).
LIVE_CHECK_SECONDS = 20.0
_live_checked: dict[str, float] = {}  # instance id -> when its container was last seen connected


class BridgeError(Exception):
    """Raised for a bridge lifecycle failure the caller should surface."""


def container_name(instance_id: str) -> str:
    return f"eai-wa-bridge-{instance_id}"


def volume_name(instance_id: str) -> str:
    return f"eai-wa-store-{instance_id}"


async def _orchestrator(method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
    settings = get_backend_settings()
    if not settings.WHATSAPP_ORCHESTRATOR_API_KEY:
        raise BridgeError(
            "WhatsApp isn't configured on this deployment — WHATSAPP_ORCHESTRATOR_API_KEY is unset."
        )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                f"{settings.WHATSAPP_ORCHESTRATOR_URL}{path}",
                json=json,
                params=params,
                headers={"X-API-Key": settings.WHATSAPP_ORCHESTRATOR_API_KEY},
            )
    except httpx.HTTPError as exc:
        raise BridgeError(f"WhatsApp orchestrator unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise BridgeError(f"WhatsApp orchestrator {method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def _get_instance(db, *, server_id: str, user_id: str) -> VendorMCPBridgeInstance | None:
    return (
        await db.execute(
            select(VendorMCPBridgeInstance).where(
                VendorMCPBridgeInstance.server_id == server_id,
                VendorMCPBridgeInstance.user_id == user_id,
            )
        )
    ).scalars().first()


def _instance_token(row: VendorMCPBridgeInstance) -> str | None:
    if not row.token_encrypted:
        return None
    try:
        return decrypt_credentials(row.token_encrypted).get("token")
    except Exception:  # noqa: BLE001 — unreadable (e.g. rotated key): issue a new one
        logger.warning("Unreadable bridge token for instance %s", row.id)
        return None


async def _mirror_connected(db, row: VendorMCPBridgeInstance, connected: bool) -> None:
    """The rest of the system (catalog "connected" gating, tool search
    visibility) reads VendorMCPCredential, not this table — mirror the
    connected state there (an empty marker; there's no secret to store)."""
    from vendor.services import mcp_auth

    if connected:
        await mcp_auth.store_server_credentials(
            db,
            server_id=row.server_id,
            credentials={"_bridge": "connected"},
            tenant_id=row.tenant_id,
            user_id=row.user_id,
        )
    else:
        await mcp_auth.delete_user_credential(db, server_id=row.server_id, user_id=row.user_id)


async def start_bridge(
    db, *, server: VendorMCPServer, user_id: str, tenant_id: str | None
) -> dict:
    """Start (or resume) this user's bridge container for ``server``. Returns
    immediately — poll ``get_status`` for the QR and the connected state."""
    row = await _get_instance(db, server_id=server.id, user_id=user_id)
    if row is None:
        row = VendorMCPBridgeInstance(
            server_id=server.id,
            user_id=user_id,
            tenant_id=tenant_id,
            status="not_connected",
            data_dir="",
            port=BRIDGE_PORT,
        )
        db.add(row)
        await db.flush()

    token = _instance_token(row)
    if token is None:
        token = secrets.token_urlsafe(32)
        row.token_encrypted = encrypt_credentials({"token": token})
    row.data_dir = volume_name(row.id)
    row.port = BRIDGE_PORT

    try:
        await _orchestrator("POST", f"/instances/{row.id}/start", json={"token": token})
    except BridgeError:
        await db.rollback()
        raise
    row.status = "starting"
    row.last_error = None
    await db.commit()
    return {"status": "starting"}


def _map_status(bridge: dict) -> tuple[str, str | None, str | None]:
    """Orchestrator/bridge status -> (our status, qr, error)."""
    status = bridge.get("status") or ""
    qr = bridge.get("qr") or None
    if status == "connected":
        return "connected", None, None
    if status == "waiting_for_scan":
        return ("awaiting_qr", qr, None) if qr else ("starting", None, None)
    if status in ("starting", "created", "restarting"):
        return "starting", None, None
    if status == "timeout":
        return "error", None, _QR_TIMEOUT_ERROR
    if status == "not_started":
        return "not_connected", None, None
    if status in ("exited", "dead", "paused", "removing"):
        return "error", None, f"WhatsApp bridge container is {status}. Click connect to restart it."
    return "error", None, bridge.get("error") or f"WhatsApp bridge reported {status!r}"


async def get_status(db, *, server_id: str, user_id: str) -> dict:
    """This user's bridge status, refreshed from their container (via the
    orchestrator) and persisted — poll while 'starting'/'awaiting_qr'."""
    row = await _get_instance(db, server_id=server_id, user_id=user_id)
    if row is None or row.status == "not_connected":
        return {"status": "not_connected"}

    try:
        bridge = await _orchestrator("GET", f"/instances/{row.id}/status")
    except BridgeError as exc:
        return {"status": "error", "error": str(exc)}

    status, qr, error = _map_status(bridge)
    if status == "connected":
        _live_checked[row.id] = time.monotonic()
    else:
        _live_checked.pop(row.id, None)
    was_connected = row.status == "connected"
    if status != row.status or error != row.last_error:
        row.status = status
        row.last_error = error
        if status == "connected":
            row.last_connected_at = str(time.time())
        if (status == "connected") != was_connected:
            await _mirror_connected(db, row, status == "connected")
        await db.commit()

    out: dict = {"status": status}
    if qr:
        out["qr"] = qr
    if error:
        out["error"] = error
    return out


async def drop_dead_bridges(db, *, user_id: str, server_ids: list[str] | None = None) -> set[str]:
    """Of this user's bridges marked connected, the ones whose container is gone, stopped or logged out —
    marked so (and their "connected" marker dropped), flushed for the caller to commit.

    The row says "connected" from the last time someone looked; the container can disappear after that
    (removed by hand, a ``docker compose down -v``, a host reboot without its volume), and then every send
    failed with "Failed to resolve eai-wa-bridge-…" while the UI still said connected. Asked wherever
    "is this user connected" is answered (``mcp_auth.has_user_credential``, the catalog, a run's launch),
    at most every LIVE_CHECK_SECONDS per bridge. An orchestrator that can't be reached changes nothing:
    "unknown" isn't "gone". Returns the server ids found dead.
    """
    query = select(VendorMCPBridgeInstance).where(
        VendorMCPBridgeInstance.user_id == user_id, VendorMCPBridgeInstance.status == "connected",
    )
    if server_ids is not None:
        if not server_ids:
            return set()
        query = query.where(VendorMCPBridgeInstance.server_id.in_(server_ids))
    dead: set[str] = set()
    now = time.monotonic()
    for row in (await db.execute(query)).scalars().all():
        if now - _live_checked.get(row.id, -LIVE_CHECK_SECONDS) < LIVE_CHECK_SECONDS:
            continue
        try:
            bridge = await _orchestrator("GET", f"/instances/{row.id}/status")
        except BridgeError:
            continue
        status, _qr, error = _map_status(bridge)
        if status == "connected" or status == "starting":
            # Starting: the container is up and still booting — not proof it's gone.
            _live_checked[row.id] = now
            continue
        logger.info("WhatsApp bridge %s is %s, not connected — marking it so", row.id, status)
        row.status = "not_connected" if status in ("not_connected", "awaiting_qr") else status
        row.last_error = error or "Your WhatsApp bridge stopped. Connect again (scan the QR if asked)."
        _live_checked.pop(row.id, None)
        await _mirror_connected(db, row, False)
        dead.add(row.server_id)
    if dead:
        await db.flush()
    return dead


async def get_mcp_env(db, *, server_id: str, user_id: str) -> dict[str, str] | None:
    """Env for the stdio MCP server that talks to this user's connected
    bridge container, or None if they haven't paired one (or it's gone)."""
    await drop_dead_bridges(db, user_id=user_id, server_ids=[server_id])
    row = await _get_instance(db, server_id=server_id, user_id=user_id)
    if row is None or row.status != "connected":
        return None
    token = _instance_token(row)
    if token is None:
        return None
    return {
        "WHATSAPP_API_BASE_URL": f"http://{container_name(row.id)}:{row.port or BRIDGE_PORT}/api",
        "WHATSAPP_BRIDGE_TOKEN": token,
        "WHATSAPP_DEFAULT_COUNTRY_CODE": get_backend_settings().WHATSAPP_DEFAULT_COUNTRY_CODE,
    }


async def stop_bridge(db, *, server_id: str, user_id: str, wipe: bool) -> None:
    """Remove this user's bridge container. ``wipe=False`` keeps its session
    volume (a future connect needs no new QR); ``wipe=True`` deletes it too
    ("forget this device" — a fresh QR next time, under a new token)."""
    row = await _get_instance(db, server_id=server_id, user_id=user_id)
    if row is None:
        return
    try:
        await _orchestrator("DELETE", f"/instances/{row.id}", params={"purge": "true" if wipe else "false"})
    except BridgeError:
        logger.warning("Failed to remove WhatsApp bridge container for instance %s", row.id, exc_info=True)
        if wipe:
            raise
    if wipe:
        row.token_encrypted = None
    row.status = "not_connected"
    row.last_error = None
    await _mirror_connected(db, row, False)
    await db.commit()
