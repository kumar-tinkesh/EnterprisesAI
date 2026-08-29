"""Tests for Argon2id hashing, RS256 JWT, and JWKS."""
from __future__ import annotations

import jwt

from src.core import security


def test_hash_and_verify_password():
    hashed = security.hash_password("s3cr3t-pass")
    assert hashed != "s3cr3t-pass"
    assert hashed.startswith("$argon2")
    assert security.verify_password("s3cr3t-pass", hashed) is True
    assert security.verify_password("wrong", hashed) is False


def test_jwks_endpoint_content():
    doc = security.get_jwks()
    assert len(doc["keys"]) == 1
    key = doc["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert key["kid"]
    assert key["n"]
    assert key["e"]


def test_create_and_decode_access_token():
    token, claims = security.create_token(
        sub="user-1", tid="tenant-1", wid="ws-1", role="admin", token_type="access"
    )
    decoded = security.decode_token(token, expected_type="access")
    assert decoded["sub"] == "user-1"
    assert decoded["tid"] == "tenant-1"
    assert decoded["wid"] == "ws-1"
    assert decoded["role"] == "admin"
    assert decoded["iss"] == "testing-issuer"


def test_token_type_mismatch_raises():
    token, _ = security.create_token(
        sub="u", tid=None, wid=None, role="admin", token_type="refresh"
    )
    import pytest

    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(token, expected_type="access")


def test_tampered_token_rejected():
    token, _ = security.create_token(
        sub="u", tid=None, wid=None, role="admin", token_type="access"
    )
    header, payload, _sig = token.split(".")
    payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    import pytest

    with pytest.raises(jwt.PyJWTError):
        security.decode_token(f"{header}.{payload}._fake", expected_type="access")


def test_refresh_token_hash():
    raw = "sample_raw_refresh_token_string"
    digest = security.hash_refresh_token(raw)
    assert digest == security.hash_refresh_token(raw)
    assert digest != raw


def test_roles_helpers():
    from src.core.roles import Roles

    assert Roles.is_valid(Roles.VENDOR_ADMIN) is True
    assert Roles.is_valid("unknown_role") is False