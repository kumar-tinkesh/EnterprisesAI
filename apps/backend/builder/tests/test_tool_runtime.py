"""Tool-runtime tests against a REAL MCP server (fixtures/demo_mcp_server.py).

Servers are registered and verified through vendor's own flow
(``test_mcp_connection``), then called through the builder API as end users —
over stdio and streamable HTTP — so these cover the actual process spawning,
sessions, per-user environments and failure handling, not mocks of them.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mcp import types
from sqlalchemy import select

from src.api.deps import CurrentUser
from src.core.roles import Roles
from src.models.auth import AuditEvent

from vendor.models import MCPTool, VendorMCPServer
from vendor.services import mcp_auth, mcp_service

from builder.config import get_builder_settings
from builder.services.tool_runtime import (
    InvalidArguments,
    classify_tool,
    get_pool,
    shutdown_pool,
    validate_arguments,
)
from builder.services.tool_runtime.results import normalize_result

FIXTURE = Path(__file__).parent / "fixtures" / "demo_mcp_server.py"
INVOKE = "/api/v1/builder/tools/invoke"


@pytest_asyncio.fixture(autouse=True)
async def _runtime(monkeypatch, tmp_path):
    settings = get_builder_settings()
    monkeypatch.setattr(settings, "BUILDER_USER_HOME_ROOT", str(tmp_path / "homes"))
    monkeypatch.setattr(settings, "TOOL_SESSION_CONNECT_TIMEOUT_SECONDS", 30.0)

    async def no_embedding(tool, **_):
        return False

    monkeypatch.setattr(mcp_service, "embed_tool", no_embedding)
    yield
    await shutdown_pool()  # stop every server process this test started


async def _register(db, *, name="demo", is_global=True, transport="stdio", endpoint=None) -> VendorMCPServer:
    server = VendorMCPServer(
        name=name,
        description="demo server",
        is_global=is_global,
        transport=transport,
        auth_type="none" if transport != "stdio" else "env",
        auth_config={},
    )
    if transport == "stdio":
        server.command = sys.executable
        server.args = [str(FIXTURE)]
    else:
        server.endpoint = endpoint
        server.server_url = endpoint
    db.add(server)
    await db.flush()
    await mcp_service.test_mcp_connection(db, server=server)
    await db.commit()
    return server


async def _connect(db, server: VendorMCPServer, user: CurrentUser, **credentials) -> None:
    await mcp_auth.store_server_credentials(
        db, server_id=server.id, credentials=credentials, tenant_id=user.tenant_id, user_id=user.id
    )
    await db.commit()


async def _invoke(client, server, tool, arguments=None, **extra):
    return await client.post(INVOKE, json={"server_id": server.id, "tool_name": tool, "arguments": arguments or {}, **extra})


# ── Pure units ───────────────────────────────────────────────────────────────


def test_classification():
    assert classify_tool("get_invoices").risk == "read"
    assert classify_tool("listRepositories").risk == "read"
    assert classify_tool("send_email").risk == "edit"
    assert classify_tool("delete-row").risk == "delete"
    # Unknown verbs must ask, never run silently.
    assert classify_tool("frobnicate").risk == "edit" and classify_tool("frobnicate").reason == "default"
    # The server's hints: read-only lifts a tool to read, but never past a delete verb.
    assert classify_tool("frobnicate", {"read_only_hint": True}).risk == "read"
    assert classify_tool("remove_user", {"read_only_hint": True}).risk == "delete"
    assert classify_tool("wipe", {"read_only_hint": False, "destructive_hint": True}).risk == "delete"
    # destructive_hint alone means nothing per the spec (read_only_hint not explicitly false).
    assert classify_tool("get_rows", {"destructive_hint": True}).risk == "read"
    assert classify_tool("get_rows").needs_confirmation is False
    assert classify_tool("send_email").needs_confirmation is True


def test_argument_validation():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    validate_arguments(schema, {"a": 1})
    validate_arguments(None, {"anything": True})
    with pytest.raises(InvalidArguments) as err:
        validate_arguments(schema, {"a": "x", "b": 1})
    assert any(e.startswith("a:") for e in err.value.errors)
    with pytest.raises(InvalidArguments) as err:
        validate_arguments(schema, {})
    assert "(root)" in err.value.errors[0]


def test_result_normalization_caps_and_summarises_binary():
    result = types.CallToolResult(
        content=[
            types.TextContent(type="text", text="x" * 50),
            types.ImageContent(type="image", data="aGVsbG8=", mime_type="image/png"),
        ],
        is_error=False,
    )
    out = normalize_result(result, max_chars=20)
    assert out.truncated and out.text.startswith("x" * 20)
    assert out.content == [{"type": "text"}, {"type": "image", "mime_type": "image/png", "bytes": 6}]

    structured_only = types.CallToolResult(content=[], structured_content={"sum": 3}, is_error=False)
    out = normalize_result(structured_only, max_chars=1000)
    assert out.structured == {"sum": 3} and '"sum": 3' in out.text


# ── Verification stores the server's hints ──────────────────────────────────


async def test_verification_stores_annotations(db):
    server = await _register(db)
    tools = {t.name: t for t in (await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server.id))).scalars()}
    assert {"echo", "send_note", "wipe", "get_flaky"} <= set(tools)
    assert tools["echo"].annotations == {"read_only_hint": True}
    assert tools["wipe"].annotations["destructive_hint"] is True
    assert tools["send_note"].annotations in (None, {})


# ── Invoking over stdio ──────────────────────────────────────────────────────


async def test_invoke_read_tool_and_reuse_session(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user, DEMO_TOKEN="alpha")

    r = await _invoke(tenant_client, server, "echo", {"text": "namaste"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "namaste" and body["is_error"] is False
    assert body["risk"] == {"risk": "read", "reason": "annotation", "needs_confirmation": False}
    assert body["attempts"] == 1

    first = (await _invoke(tenant_client, server, "whoami")).json()["structured"]
    second = (await _invoke(tenant_client, server, "whoami")).json()["structured"]
    assert first["pid"] == second["pid"]  # pooled: one process for many calls
    assert first["token"] == "alpha"
    assert get_pool().stats()["open"] == 1


async def test_users_are_isolated(db, tenant_client, tenant_user, make_user_client):
    server = await _register(db)
    other = CurrentUser(id="tu_2", email="b@x.io", full_name="B", role=Roles.TENANT_USER, tenant_id=tenant_user.tenant_id)
    other_client = await make_user_client(other)
    await _connect(db, server, tenant_user, DEMO_TOKEN="alpha")
    await _connect(db, server, other, DEMO_TOKEN="beta")

    mine = (await _invoke(tenant_client, server, "whoami")).json()["structured"]
    theirs = (await _invoke(other_client, server, "whoami")).json()["structured"]
    assert (mine["token"], theirs["token"]) == ("alpha", "beta")
    assert mine["pid"] != theirs["pid"]
    assert mine["home"] != theirs["home"]
    assert Path(mine["home"]).name == "tu_1" and Path(theirs["home"]).name == "tu_2"
    assert oct(Path(mine["home"]).stat().st_mode & 0o777) == "0o700"


async def test_reconnecting_with_new_credentials_starts_a_new_session(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user, DEMO_TOKEN="old")
    assert (await _invoke(tenant_client, server, "whoami")).json()["structured"]["token"] == "old"
    await _connect(db, server, tenant_user, DEMO_TOKEN="new")
    assert (await _invoke(tenant_client, server, "whoami")).json()["structured"]["token"] == "new"


async def test_data_changing_tools_need_confirmation(db, tenant_client, tenant_user, tmp_path):
    server = await _register(db)
    await _connect(db, server, tenant_user)

    r = await _invoke(tenant_client, server, "send_note", {"text": "hello"})
    assert r.status_code == 409 and r.json()["error"] == "ConfirmationRequired" and r.json()["risk"] == "edit"
    notes = tmp_path / "homes" / "tu_1" / "notes.txt"
    assert not notes.exists()  # nothing ran

    r = await _invoke(tenant_client, server, "send_note", {"text": "hello"}, confirm=True)
    assert r.status_code == 200 and r.json()["text"] == "1 notes"
    assert notes.read_text() == "hello\n"

    r = await _invoke(tenant_client, server, "wipe")
    assert r.status_code == 409 and r.json()["risk"] == "delete"


async def test_refusals(db, tenant_client, tenant_user, admin_client):
    server = await _register(db)

    r = await _invoke(tenant_client, server, "echo", {"text": "hi"})
    assert r.status_code == 409 and r.json()["error"] == "NotConnected" and r.json()["server_id"] == server.id

    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "echo", {"text": 5})
    assert r.status_code == 422 and r.json()["errors"]
    r = await _invoke(tenant_client, server, "no_such_tool")
    assert r.status_code == 404

    private = await _register(db, name="private", is_global=False)
    r = await _invoke(tenant_client, private, "echo", {"text": "hi"})
    assert r.status_code == 404  # neither global nor granted to this tenant

    r = await _invoke(admin_client, server, "echo", {"text": "hi"})
    assert r.status_code == 403
    assert get_pool().stats()["open"] == 0  # no refused call started a process


async def test_tool_error_is_a_result_not_a_failure(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "fail")
    assert r.status_code == 200
    assert r.json()["is_error"] is True and "boom" in r.json()["text"]
    # The session survives a tool error.
    assert (await _invoke(tenant_client, server, "echo", {"text": "still here"})).json()["text"] == "still here"


async def test_timeout_evicts_the_session(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    pid = (await _invoke(tenant_client, server, "whoami")).json()["structured"]["pid"]

    r = await _invoke(tenant_client, server, "wait_for", {"seconds": 10}, timeout_seconds=1)
    assert r.status_code == 504 and r.json()["error"] == "ToolTimeout"

    assert (await _invoke(tenant_client, server, "whoami")).json()["structured"]["pid"] != pid


async def test_read_tool_is_retried_once_after_a_crash(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "get_flaky")
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "recovered" and r.json()["attempts"] == 2


async def test_write_tool_is_never_retried_after_a_crash(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "post_and_crash", {"text": "x"}, confirm=True)
    assert r.status_code == 502, r.text
    assert r.json()["error"] == "ToolUnavailable" and r.json()["may_have_run"] is True
    # The broken session is gone; the next call gets a fresh, working one.
    assert (await _invoke(tenant_client, server, "echo", {"text": "ok"})).json()["text"] == "ok"


async def test_server_that_cannot_start(db, tenant_client, tenant_user):
    server = await _register(db)
    server.args = [str(FIXTURE.parent / "missing.py")]
    await db.commit()
    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "echo", {"text": "hi"})
    assert r.status_code == 502 and r.json()["may_have_run"] is False


async def test_idle_sessions_are_reaped(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    await _invoke(tenant_client, server, "echo", {"text": "hi"})
    pool = get_pool()
    assert await pool.reap_idle(now=time.monotonic()) == 0  # just used
    assert await pool.reap_idle(now=time.monotonic() + 10_000) == 1
    assert pool.stats()["open"] == 0


async def test_list_server_tools(db, tenant_client, tenant_user):
    server = await _register(db)
    r = await tenant_client.get(f"/api/v1/builder/servers/{server.id}/tools")
    body = r.json()
    assert body["connected"] is False
    risks = {t["name"]: t["risk"]["risk"] for t in body["tools"]}
    assert risks["echo"] == "read" and risks["send_note"] == "edit" and risks["wipe"] == "delete"
    await _connect(db, server, tenant_user)
    assert (await tenant_client.get(f"/api/v1/builder/servers/{server.id}/tools")).json()["connected"] is True


async def test_invocations_are_audited_without_arguments(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    await _invoke(tenant_client, server, "echo", {"text": "secret-value"})
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action == "builder.tool_invoke"))).scalars().all()
    assert len(events) == 1
    assert "tool=echo" in events[0].detail and "outcome=ok" in events[0].detail
    assert "secret-value" not in events[0].detail
    assert events[0].tenant_id == tenant_user.tenant_id


# ── Invoking over streamable HTTP ────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(FIXTURE), "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


async def test_invoke_over_streamable_http(db, tenant_client, tenant_user, http_server):
    server = await _register(db, name="demo-http", transport="streamable_http", endpoint=http_server)
    await _connect(db, server, tenant_user)
    r = await _invoke(tenant_client, server, "echo", {"text": "over http"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "over http"
    r = await _invoke(tenant_client, server, "add_numbers", {"a": 2, "b": 3}, confirm=True)
    assert r.json()["structured"] == {"sum": 5}


async def test_concurrent_calls_share_one_session(db, tenant_client, tenant_user):
    server = await _register(db)
    await _connect(db, server, tenant_user)
    await _invoke(tenant_client, server, "echo", {"text": "warm"})
    start = time.monotonic()
    results = await asyncio.gather(*(_invoke(tenant_client, server, "wait_for", {"seconds": 1}) for _ in range(3)))
    assert all(r.status_code == 200 for r in results)
    assert get_pool().stats()["open"] == 1
    assert time.monotonic() - start < 2.9  # not serialised one after another


def test_only_the_sdks_own_connection_closed_counts_as_a_broken_transport():
    from mcp.shared.exceptions import MCPError

    from builder.services.tool_runtime.invoke import _connection_closed

    assert _connection_closed(MCPError(code=-32000, message="Connection closed"))
    # A server's own generic error reply shares the code but is a real answer.
    assert not _connection_closed(MCPError(code=-32000, message="Rate limited, try later"))
    assert not _connection_closed(MCPError(code=-32602, message="Connection closed"))
