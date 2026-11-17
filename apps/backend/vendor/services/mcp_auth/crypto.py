"""Credential encryption and decryption module for mcp_auth using Fernet."""
from __future__ import annotations

import json
from cryptography.fernet import Fernet


class McpAuthError(Exception):
    """Raised when credentials for an auth-protected MCP server cannot be resolved."""


def _fernet() -> Fernet:
    from base64 import urlsafe_b64encode
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from src.config import get_settings

    settings = get_settings()
    # Prefer the dedicated secret; fall back to the (always generated)
    # JWT private key so the deployment needs no extra configuration.
    secret = settings.MCP_CREDENTIALS_SECRET or settings.JWT_PRIVATE_KEY
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mcp_credentials_salt",
        iterations=100_000,
    )
    return Fernet(urlsafe_b64encode(kdf.derive(secret.encode())))


def encrypt_credentials(credentials: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(credentials, sort_keys=True).encode()).decode()


def decrypt_credentials(encrypted: str) -> dict[str, str]:
    try:
        return json.loads(_fernet().decrypt(encrypted.encode()).decode())
    except Exception as exc:  # noqa: BLE001
        raise McpAuthError(f"Failed to decrypt stored MCP credentials: {exc}") from exc
