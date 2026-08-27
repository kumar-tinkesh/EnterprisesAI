"""Security primitives: Argon2id password hashing, RSA keypair management,
RS256 token sign/verify, public JWKS publishing, and CSRF signing."""
from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pwdlib import PasswordHash

from src.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Password hashing (Argon2id via pwdlib)
# ---------------------------------------------------------------------------

_password_hash = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """Hash a plain-text password with Argon2id (OWASP recommended)."""
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against an Argon2id hash (constant-time)."""
    try:
        return _password_hash.verify(plain, hashed)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# RSA keypair management (persisted under .keys/, git-ignored)
# ---------------------------------------------------------------------------

_KEY_DIR = get_settings().key_dir
_PRIVATE_KEY_FILE = _KEY_DIR / "private_key.pem"
_PUBLIC_KEY_FILE = _KEY_DIR / "public_key.pem"


def _generate_keypair() -> tuple[str, str]:
    """Generate a new RSA-2048 keypair, persist PEM files, return (private, public)."""
    _KEY_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    _PRIVATE_KEY_FILE.write_text(private_pem)
    _PRIVATE_KEY_FILE.chmod(0o600)
    _PUBLIC_KEY_FILE.write_text(public_pem)
    return private_pem, public_pem


def _ensure_keys(settings: Settings) -> tuple[str, str]:
    """Return (private_pem, public_pem) from config or .keys/ (auto-generate)."""
    if settings.JWT_PRIVATE_KEY and settings.JWT_PUBLIC_KEY:
        return settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY
    if _PRIVATE_KEY_FILE.exists() and _PUBLIC_KEY_FILE.exists():
        return _PRIVATE_KEY_FILE.read_text(), _PUBLIC_KEY_FILE.read_text()
    return _generate_keypair()


def _load_private_key(settings: Settings) -> rsa.RSAPrivateKey:
    private_pem, _ = _ensure_keys(settings)
    return serialization.load_pem_private_key(private_pem.encode(), password=None)


def get_keypair() -> tuple[str, str]:
    """Return the current (private_pem, public_pem)."""
    return _ensure_keys(get_settings())


def _key_id(public_pem: str) -> str:
    """Derive a stable kid (JWK-style thumbprint) from the public key PEM."""
    digest = hashlib.sha256(public_pem.encode()).digest()
    return base64.urlsafe_b64encode(digest[:15]).rstrip(b"=").decode()


def _b64u_int(value: int) -> str:
    """Big-int -> base64url (no padding), per RFC 7518."""
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def get_jwks() -> dict:
    """Build the public JWKS document published at ``/.well-known/jwks.json``."""
    _, public_pem = get_keypair()
    settings = get_settings()
    public_key = serialization.load_pem_public_key(public_pem.encode())
    public_numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": settings.JWT_ALGORITHM,
                "kid": _key_id(public_pem),
                "n": _b64u_int(public_numbers.n),
                "e": _b64u_int(public_numbers.e),
            }
        ]
    }


# ---------------------------------------------------------------------------
# RS256 JWT creation / validation
# ---------------------------------------------------------------------------


def create_token(
    *,
    sub: str,
    tid: str | None,
    wid: str | None,
    role: str,
    token_type: str = "access",
    expires_minutes: int | None = None,
) -> tuple[str, dict]:
    """Create a signed RS256 JWT and return (token, claims)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_minutes is None:
        if token_type == "refresh":
            expires_minutes = settings.JWT_REFRESH_TOKEN_EXPIRE_MINUTES
        else:
            expires_minutes = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    ts = int(now.timestamp())

    claims = {
        "sub": sub,
        "tid": tid,
        "wid": wid,
        "role": role,
        "type": token_type,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": ts,
        "nbf": ts,
        "exp": ts + expires_minutes * 60,
        "jti": uuid.uuid4().hex,
    }
    key = _load_private_key(settings)
    _, public_pem = get_keypair()
    token = jwt.encode(
        claims,
        key,
        algorithm=settings.JWT_ALGORITHM,
        headers={"kid": _key_id(public_pem)},
    )
    return token, claims


def create_token_pair(
    *, sub: str, tid: str | None, wid: str | None, role: str
) -> dict[str, str]:
    """Issue an access + refresh token pair for a subject."""
    access, _ = create_token(sub=sub, tid=tid, wid=wid, role=role, token_type="access")
    refresh, _ = create_token(
        sub=sub, tid=tid, wid=wid, role=role, token_type="refresh"
    )
    return {"access_token": access, "refresh_token": refresh}


def decode_token(token: str, *, expected_type: str | None = None) -> dict:
    """Validate an RS256 JWT and return its claims. Raises on failure."""
    settings = get_settings()
    _, public_pem = get_keypair()
    claims = jwt.decode(
        token,
        public_pem,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["sub", "exp", "iat", "jti"]},
    )
    if expected_type and claims.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Expected token of type '{expected_type}', got '{claims.get('type')}'"
        )
    return claims


# ---------------------------------------------------------------------------
# Refresh token helpers
# ---------------------------------------------------------------------------


def hash_refresh_token(token: str) -> str:
    """Return a one-way digest used to persist a refresh token securely."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    """Return a cryptographically random opaque refresh token string."""
    return secrets.token_urlsafe(64)


# ---------------------------------------------------------------------------
# CSRF (double-submit cookie validation) via itsdangerous
# ---------------------------------------------------------------------------


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.CSRF_SECRET_KEY)


def sign_csrf(data: str = "csrf") -> str:
    """Sign a CSRF value to store in the cookie / double-submit form field."""
    return _serializer(get_settings()).dumps(data)


def verify_csrf(token: str, max_age: int | None = None) -> bool:
    """Validate a signed CSRF token (time-limited)."""
    settings = get_settings()
    max_age = max_age or settings.CSRF_COOKIE_AGE
    try:
        _serializer(settings).loads(token, max_age=max_age)
        return True
    except BadSignature:
        return False