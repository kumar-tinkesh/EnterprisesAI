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


# ── clock-skew (leeway) tolerance ────────────────────────────────────


def test_decode_token_tolerates_recently_expired_token():
    """exp a few minutes in the past is accepted within JWT_LEEWAY_SECONDS."""
    token, _ = security.create_token(
        sub="u", tid=None, wid=None, role="admin", token_type="access",
        expires_minutes=-4,  # 240 s in the past, default leeway is 300 s
    )
    decoded = security.decode_token(token)
    assert decoded["sub"] == "u"


def test_decode_token_rejects_token_expired_beyond_leeway():
    """exp far in the past (beyond leeway) still raises ExpiredSignatureError."""
    import pytest

    token, _ = security.create_token(
        sub="u", tid=None, wid=None, role="admin", token_type="access",
        expires_minutes=-10,  # 600 s in the past, default leeway is 300 s
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)


def test_decode_token_tolerates_future_nbf_within_leeway():
    """nbf slightly in the future (within leeway) validates instead of raising."""
    import time
    import uuid

    from src.config import get_settings

    settings = get_settings()
    ts = int(time.time())
    claims = {
        "sub": "u",
        "tid": None,
        "wid": None,
        "role": "admin",
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": ts,
        "nbf": ts + 120,  # 2 min in the future, inside the 300 s leeway
        "exp": ts + settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "jti": uuid.uuid4().hex,
    }
    key = security._load_private_key(settings)
    _, public_pem = security.get_keypair()
    token = jwt.encode(
        claims, key, algorithm=settings.JWT_ALGORITHM,
        headers={"kid": security._key_id(public_pem)},
    )
    decoded = security.decode_token(token, expected_type="access")
    assert decoded["sub"] == "u"


def test_roles_helpers():
    from src.core.roles import Roles

    assert Roles.is_valid(Roles.VENDOR_ADMIN) is True
    assert Roles.is_valid("unknown_role") is False