"""Standards-driven detection tests for ``mcp_detect`` (no real network).

All HTTP is served by an ``httpx.MockTransport`` patched into the module's
client factory, covering: open servers, Basic challenges, custom-scheme API
key challenges, Bearer challenges with full RFC 9728 → RFC 8414 OAuth
metadata discovery, and unreachable servers.
"""
from __future__ import annotations


import httpx
import pytest

from vendor.services import mcp_detect
from vendor.services.mcp_detect import detect_mcp_server

_URL = "https://mcp.example.com/invoice"


def _patch_client(monkeypatch, handler):
    """Make mcp_detect use a MockTransport-backed client factory."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient  # capture before patching the module attr

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return real_client(transport=transport)

    monkeypatch.setattr(mcp_detect.httpx, "AsyncClient", factory)


def _json_response(status_code, body, headers=None):
    return httpx.Response(
        status_code,
        json=body,
        headers=headers or {},
        request=httpx.Request("POST", "https://mcp.example.com"),
    )


@pytest.mark.asyncio
async def test_detect_open_server_is_none(monkeypatch):
    """200 on an unauthenticated initialize → auth_type none, no fields."""
    mcp_result = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mcp.example.com"
        return _json_response(200, mcp_result, {"content-type": "application/json"})

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["ok"] is True
    assert result["auth_type"] == "none"
    assert result["auth_required"] is False
    assert result["credential_fields"] == []
    assert result["oauth"] == {}


@pytest.mark.asyncio
async def test_detect_basic_challenge(monkeypatch):
    """WWW-Authenticate: Basic → auth_type basic with username/password fields."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            401,
            {"error": "unauthorized"},
            {"WWW-Authenticate": 'Basic realm="mcp"'},
        )

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["ok"] is True
    assert result["auth_type"] == "basic"
    assert result["reachable"] is True
    field_names = [f["name"] for f in result["credential_fields"]]
    assert field_names == ["username", "password"]
    assert result["oauth"] == {}


@pytest.mark.asyncio
async def test_detect_custom_scheme_is_api_key(monkeypatch):
    """A custom challenge scheme (ApiKey) → auth_type api_key."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            401, {"error": "unauthorized"}, {"WWW-Authenticate": "ApiKey"}
        )

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["auth_type"] == "api_key"
    assert result["credential_fields"][0]["name"] == "api_key"


@pytest.mark.asyncio
async def test_detect_bearer_without_metadata_stays_bearer(monkeypatch):
    """A Bearer challenge with NO OAuth metadata → bearer (static token/JWT),
    never guessed from the URL."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if ".well-known" in request.url.path:
            return httpx.Response(404, request=request)
        return _json_response(
            401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"}
        )

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["auth_type"] == "bearer"
    assert result["oauth"] == {}
    # Well-known metadata was probed (standards-driven) but found nothing.
    assert any(".well-known" in c for c in calls)


@pytest.mark.asyncio
async def test_detect_oauth_metadata_discovery(monkeypatch):
    """Bearer challenge → RFC 9728 protected-resource → RFC 8414 AS metadata
    → auth_type oauth2 with token_endpoint surfaced in the ``oauth`` block."""
    as_metadata = {
        "issuer": "https://auth.example.com",
        "token_endpoint": "https://auth.example.com/oauth/token",
        "registration_endpoint": "https://auth.example.com/oauth/register",
        "scopes_supported": ["mcp:tools", "email.read"],
        "grant_types_supported": ["client_credentials", "refresh_token"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/oauth-protected-resource":
            return _json_response(
                200,
                {
                    "resource": "https://mcp.example.com",
                    "authorization_servers": ["https://auth.example.com"],
                    "scopes_supported": ["mcp:tools", "email.read"],
                },
            )
        if request.url.host == "auth.example.com" and request.url.path.endswith(
            "oauth-authorization-server"
        ):
            return _json_response(200, as_metadata)
        return _json_response(
            401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"}
        )

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["auth_type"] == "oauth2"
    assert result["oauth"]["token_endpoint"] == "https://auth.example.com/oauth/token"
    assert result["oauth"]["registration_endpoint"] == (
        "https://auth.example.com/oauth/register"
    )
    assert result["oauth"]["grant_types_supported"] == [
        "client_credentials",
        "refresh_token",
    ]
    assert result["oauth_scopes"] == ["mcp:tools", "email.read"]
    field_names = [f["name"] for f in result["credential_fields"]]
    assert "client_id" in field_names and "client_secret" in field_names


@pytest.mark.asyncio
async def test_detect_resource_metadata_challenge_param(monkeypatch):
    """RFC 9728 §5.1: resource_metadata="…" in the challenge is followed."""
    as_metadata = {
        "issuer": "https://sso.example.com",
        "token_endpoint": "https://sso.example.com/token",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcp.example.com" and request.url.path == (
            "/.well-known/oauth-protected-resource"
        ):
            return _json_response(
                200,
                {
                    "resource": "https://mcp.example.com",
                    "authorization_servers": ["https://sso.example.com"],
                },
            )
        if request.url.host == "sso.example.com" and request.url.path == (
            "/.well-known/oauth-authorization-server"
        ):
            return _json_response(200, as_metadata)
        return _json_response(
            401,
            {"error": "unauthorized"},
            {
                "WWW-Authenticate": (
                    'Bearer realm="mcp", '
                    'resource_metadata="https://mcp.example.com/.well-known/'
                    'oauth-protected-resource"'
                )
            },
        )

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["auth_type"] == "oauth2"
    assert result["oauth"]["token_endpoint"] == "https://sso.example.com/token"


@pytest.mark.asyncio
async def test_detect_unreachable_reports_unknown(monkeypatch):
    """Everything 404, no metadata → unknown with probe evidence (no URL
    pattern guessing — an unknown host must stay unknown)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    _patch_client(monkeypatch, handler)
    result = await detect_mcp_server(_URL)
    assert result["auth_type"] == "unknown"
    assert result["reachable"] is False
    assert result["error"] and "unreachable" in result["error"]


def test_resource_metadata_url_parsing():
    www = 'Bearer realm="x", resource_metadata="https://r.example.com/meta"'
    assert mcp_detect._resource_metadata_url(www) == "https://r.example.com/meta"
    assert mcp_detect._resource_metadata_url("Bearer") is None
    assert mcp_detect._resource_metadata_url(None) is None
