"""OIDC / SSO helpers: discovery, PKCE, authorization URL building, token
exchange, and RS256 ``id_token`` verification against the provider JWKS."""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any

import httpx
import jwt
from jwt import algorithms

from src.config import get_settings

__all__ = [
    "DISCOVERY_CACHE",
    "pkce_pair",
    "build_authorization_url",
    "exchange_code",
    "verify_id_token",
    "generate_state",
]

# Simple in-memory cache of OIDC discovery documents (process lifetime).
DISCOVERY_CACHE: dict[str, dict[str, Any]] = {}


def _b64(value: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(verifier)
    return verifier, challenge


async def get_discovery(
    session: httpx.AsyncClient, discovery_url: str | None = None
) -> dict[str, Any]:
    """Fetch (and cache) the OIDC discovery document from the provider."""
    settings = get_settings()
    url = discovery_url or settings.SSO_DISCOVERY_URL
    cached = DISCOVERY_CACHE.get(url)
    if cached is not None:
        return cached
    response = await session.get(url)
    response.raise_for_status()
    doc: dict[str, Any] = response.json()
    DISCOVERY_CACHE[url] = doc
    return doc



async def build_authorization_url(
    session: httpx.AsyncClient,
    *,
    state: str,
    code_challenge: str,
    discovery: dict[str, Any] | None = None,
) -> str:
    """Build the OIDC authorization URL (authorization code + PKCE flow)."""
    settings = get_settings()
    if discovery is None:
        discovery = await get_discovery(session)
    params = {
        "response_type": "code",
        "client_id": settings.SSO_CLIENT_ID,
        "redirect_uri": settings.SSO_REDIRECT_URI,
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery['authorization_endpoint']}?{httpx.QueryParams(params)}"


async def exchange_code(
    session: httpx.AsyncClient,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exchange the authorization code for tokens at the token endpoint."""
    settings = get_settings()
    if discovery is None:
        discovery = await get_discovery(session)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or settings.SSO_REDIRECT_URI,
        "client_id": settings.SSO_CLIENT_ID,
        "client_secret": settings.SSO_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }
    response = await session.post(discovery["token_endpoint"], data=data)
    response.raise_for_status()
    return response.json()


async def verify_id_token(
    id_token: str,
    session: httpx.AsyncClient | None = None,
    *,
    discovery: dict[str, Any] | None = None,
    jwks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an OIDC ``id_token`` (RS256) against the provider's JWKS.

    ``discovery`` / ``jwks`` may be injected to skip network I/O (useful for
    tests). When omitted they are fetched over the provided ``session``.
    """
    settings = get_settings()
    if discovery is None:
        if session is None:
            raise ValueError("session is required when discovery is not provided")
        discovery = await get_discovery(session)
    if jwks is None:
        if session is None:
            raise ValueError("session is required when jwks is not provided")
        resp = await session.get(discovery["jwks_uri"])
        resp.raise_for_status()
        jwks = resp.json()

    unverified = jwt.get_unverified_header(id_token)
    kid = unverified.get("kid")
    key = next(
        (k for k in jwks["keys"] if k.get("kid") == kid or (not kid and not k.get("kid"))),
        None,
    )
    if key is None:
        raise ValueError("No matching signing key found in JWKS")

    public_key = algorithms.RSAAlgorithm.from_jwk(key)
    options: dict[str, Any] = {
        "verify_aud": bool(settings.SSO_CLIENT_ID),
        "require": ["exp", "iss", "sub", "iat"],
    }
    payload = jwt.decode(
        id_token,
        public_key,
        algorithms=[key.get("alg", "RS256")],
        audience=settings.SSO_CLIENT_ID or None,
        options=options,
    )
    return payload


def generate_state() -> str:
    """Return a random OAuth state value for CSRF protection of the flow."""
    return secrets.token_urlsafe(32)