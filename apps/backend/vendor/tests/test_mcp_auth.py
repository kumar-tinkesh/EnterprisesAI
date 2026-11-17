"""Tests for the native credential resolution engine (``mcp_auth``).

Covers header building for every auth type, encrypted persistence, the
OAuth2 flows (client_credentials, refresh_token with rotation, dynamic
registration), token caching, and failure paths. All HTTP is mocked via
``httpx.MockTransport`` patched into the module's client factory.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from vendor.services import mcp_auth
from vendor.services.mcp_auth import (
    McpAuthError,
    _api_key_header,
    _basic_header,
    _bearer_header,
    clear_token_cache,
    decrypt_credentials,
    encrypt_credentials,
    resolve_auth,
)

_URL = "https://mcp.example.com"
_TOKEN_ENDPOINT = "https://auth.example.com/oauth/token"


def _fake_server(auth_type="none", server_id="srv-1", oauth=None, name="Test MCP"):
    auth_config = {"auth_type": auth_type}
    if oauth is not None:
        auth_config["oauth"] = oauth
    return SimpleNamespace(
        id=server_id, name=name, auth_config=auth_config, server_url=_URL
    )


def _oauth_config(**overrides):
    meta = {
        "token_endpoint": _TOKEN_ENDPOINT,
        "registration_endpoint": None,
        "scopes_supported": ["mcp:tools"],
        "grant_types_supported": ["client_credentials", "refresh_token"],
    }
    meta.update(overrides)
    return meta


def _patch_token_endpoint(monkeypatch, responder):
    """Patch the module's client factory with a MockTransport whose token
    endpoint is handled by ``responder(request, form)``."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        form = request.content.decode()
        return responder(request, form)

    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return httpx.AsyncClient(transport=transport)

    monkeypatch.setattr(mcp_auth, "_new_client", factory)
    return calls


# ── header builders ──────────────────────────────────────────────────


def test_basic_header():
    headers = _basic_header({"username": "u@x.io", "password": "p@ss"})
    expected = base64.b64encode(b"u@x.io:p@ss").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_api_key_header_default_and_custom_name():
    assert _api_key_header({"api_key": "sk-123"}) == {"X-API-Key": "sk-123"}
    assert _api_key_header({"api_key": "sk-123", "header_name": "X-Api"}) == {
        "X-Api": "sk-123"
    }
    assert _api_key_header({"api_key": "tok", "header_name": "Authorization"}) == {
        "Authorization": "Bearer tok"
    }
    assert _api_key_header({}) == {}


def test_bearer_header_idempotent_prefix():
    assert _bearer_header("abc") == {"Authorization": "Bearer abc"}
    assert _bearer_header("Bearer abc") == {"Authorization": "Bearer abc"}


def test_encrypt_decrypt_roundtrip():
    secrets = {"client_secret": "s3cr3t", "refresh_token": "rt-1"}
    encrypted = encrypt_credentials(secrets)
    assert "s3cr3t" not in encrypted  # never stored in plaintext
    assert decrypt_credentials(encrypted) == secrets


# ── resolve_auth per auth type ───────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_none_and_env_build_no_headers():
    for auth_type in ("none", "env"):
        auth = await resolve_auth(
            None,
            server_id="srv-1",
            server_url=_URL,
            auth_config={"auth_type": auth_type},
            credentials={"api_key": "ignored"},
        )
        assert auth["headers"] == {}
        assert auth["auth_type"] == auth_type


@pytest.mark.asyncio
async def test_resolve_api_key():
    auth = await resolve_auth(
        None,
        server_id="srv-1",
        server_url=_URL,
        auth_config={"auth_type": "api_key"},
        credentials={"api_key": "sk-123"},
    )
    assert auth["headers"] == {"X-API-Key": "sk-123"}


@pytest.mark.asyncio
async def test_resolve_basic():
    auth = await resolve_auth(
        None,
        server_id="srv-1",
        server_url=_URL,
        auth_config={"auth_type": "basic"},
        credentials={"username": "u", "password": "p"},
    )
    expected = base64.b64encode(b"u:p").decode()
    assert auth["headers"] == {"Authorization": f"Basic {expected}"}


@pytest.mark.asyncio
async def test_resolve_bearer_from_jwt():
    auth = await resolve_auth(
        None,
        server_id="srv-1",
        server_url=_URL,
        auth_config={"auth_type": "bearer"},
        credentials={"jwt": "eyJhbGciOi.payload.sig"},
    )
    assert auth["headers"] == {"Authorization": "Bearer eyJhbGciOi.payload.sig"}


@pytest.mark.asyncio
async def test_resolve_unknown_passthrough():
    auth = await resolve_auth(
        None,
        server_id="srv-1",
        server_url=_URL,
        auth_config={"auth_type": "unknown"},
        credentials={"x-api-key": "z", "not_a_header": "y"},
    )
    assert auth["headers"] == {"x-api-key": "z"}


# ── OAuth2 flows ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_token_cache()
    yield
    clear_token_cache()


def _token_endpoint_calls(monkeypatch, responder):
    transport = httpx.MockTransport(responder)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return httpx.AsyncClient(transport=transport)

    monkeypatch.setattr(mcp_auth, "_new_client", factory)


@pytest.mark.asyncio
async def test_oauth2_client_credentials_grant(monkeypatch):
    """client_id + client_secret → native token acquisition via Basic auth."""

    def responder(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert form["grant_type"] == "client_credentials"
        assert form["scope"] == "mcp:tools"
        expected = base64.b64encode(b"cid:cs3cr3t").decode()
        assert request.headers["Authorization"] == f"Basic {expected}"
        return httpx.Response(
            200, json={"access_token": "tok-1", "expires_in": 3600}, request=request
        )

    _token_endpoint_calls(monkeypatch, responder)
    auth = await resolve_auth(
        None,
        server_id="srv-1",
        server_url=_URL,
        auth_config={"auth_type": "oauth2", "oauth": _oauth_config()},
        credentials={"client_id": "cid", "client_secret": "cs3cr3t"},
    )
    assert auth["headers"] == {"Authorization": "Bearer tok-1"}
    assert auth["token_source"] == "client_credentials"


@pytest.mark.asyncio
async def test_oauth2_token_is_cached(monkeypatch):
    """A second resolve within the token's lifetime performs no HTTP."""
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"access_token": "tok-1", "expires_in": 3600}, request=request
        )

    _token_endpoint_calls(monkeypatch, responder)
    config = {"auth_type": "oauth2", "oauth": _oauth_config()}
    creds = {"client_id": "cid", "client_secret": "cs"}
    for _ in range(2):
        auth = await resolve_auth(
            None, server_id="srv-1", server_url=_URL,
            auth_config=config, credentials=creds,
        )
        assert auth["headers"] == {"Authorization": "Bearer tok-1"}
    assert len(calls) == 1  # second resolve was served from cache


@pytest.mark.asyncio
async def test_oauth2_refresh_token_grant_rotates(monkeypatch, db):
    """refresh_token grant is preferred and the rotated token is re-persisted."""

    def responder(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "rt-old"
        return httpx.Response(
            200,
            json={
                "access_token": "tok-2",
                "expires_in": 3600,
                "refresh_token": "rt-new",
            },
            request=request,
        )

    _token_endpoint_calls(monkeypatch, responder)
    server = _fake_server("oauth2", server_id="srv-db", oauth=_oauth_config())
    await mcp_auth.store_server_credentials(
        db, server_id="srv-db", credentials={"refresh_token": "rt-old"}
    )
    auth = await resolve_auth(
        db,
        server_id="srv-db",
        server_url=_URL,
        auth_config=server.auth_config,
        credentials={"refresh_token": "rt-old"},
    )
    assert auth["headers"] == {"Authorization": "Bearer tok-2"}
    assert auth["token_source"] == "refresh_token"
    stored = await mcp_auth.load_server_credentials(db, server_id="srv-db")
    assert stored["refresh_token"] == "rt-new"


@pytest.mark.asyncio
async def test_oauth2_dynamic_client_registration(monkeypatch):
    """No client_id + a registration_endpoint → RFC 7591 registration, then
    client_credentials — all driven by discovered metadata."""
    registered: dict = {}

    def token_responder(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert form["grant_type"] == "client_credentials"
        assert form["scope"] == "mcp:tools"
        return httpx.Response(
            200, json={"access_token": "tok-3", "expires_in": 3600}, request=request
        )

    async def fake_register(oauth, server_name):
        assert oauth["registration_endpoint"] == "https://auth.example.com/register"
        assert server_name == "Test MCP"
        registered.update({"client_id": "dyn-1", "client_secret": "dyn-s"})
        return dict(registered)

    _token_endpoint_calls(monkeypatch, token_responder)
    monkeypatch.setattr(mcp_auth, "_dynamically_register_client", fake_register)
    auth = await resolve_auth(
        None,
        server_id="srv-dyn",
        server_url=_URL,
        auth_config={
            "auth_type": "oauth2",
            "oauth": _oauth_config(
                registration_endpoint="https://auth.example.com/register"
            ),
        },
        credentials={},
        server_name="Test MCP",
    )
    assert registered == {"client_id": "dyn-1", "client_secret": "dyn-s"}
    assert auth["token_source"] == "dynamic_registration"
    assert auth["headers"] == {"Authorization": "Bearer tok-3"}


@pytest.mark.asyncio
async def test_oauth2_passthrough_and_failure():
    """No grant inputs → passthrough of a pre-obtained token; with nothing at
    all → McpAuthError."""
    server = _fake_server("oauth2", server_id="srv-pt", oauth=_oauth_config())
    auth = await resolve_auth(
        None,
        server_id="srv-pt",
        server_url=_URL,
        auth_config=server.auth_config,
        credentials={"access_token": "pre-obtained-jwt"},
    )
    assert auth["headers"] == {"Authorization": "Bearer pre-obtained-jwt"}
    assert auth["token_source"] == "passthrough"

    with pytest.raises(McpAuthError):
        await resolve_auth(
            None, server_id="srv-bad", server_url=_URL,
            auth_config=server.auth_config, credentials={},
        )


@pytest.mark.asyncio
async def test_stored_credentials_override_and_merge(db):
    """Stored encrypted credentials are used; request credentials win."""
    await mcp_auth.store_server_credentials(
        db, server_id="srv-merge", credentials={"api_key": "stored", "extra": "x"}
    )
    auth = await resolve_auth(
        db,
        server_id="srv-merge",
        server_url=_URL,
        auth_config={"auth_type": "api_key"},
        credentials={"api_key": "fresh"},
    )
    assert auth["headers"] == {"X-API-Key": "fresh"}
    assert auth["credentials"]["extra"] == "x"  # stored values still merged in


