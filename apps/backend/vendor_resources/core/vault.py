"""AES-256-GCM secret encryption for vendor tool credentials.

Only a reference (``vault_secret_ref``) is ever stored on a ``vendor_tools``
row; any plaintext secret is encrypted here and stored out-of-band by the
caller (e.g. in an external secrets manager keyed by the reference). This
module provides the symmetric envelope used to seal those secrets.

Key resolution
──────────────
* ``VENDOR_VAULT_KEY`` env var: a 32-byte urlsafe-base64 string.
* If unset/empty, a deterministic dev-only key is derived and a warning is
  logged. This must NEVER be relied upon in production.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("vendor_resources.vault")

_DEV_KEY_SEED = b"enterprise-ai-dev-vault-key"
_PREFIX = "v1:"


class Vault:
    """AES-256-GCM symmetric encryption envelope."""

    def __init__(self, key_b64: str | None = None) -> None:
        if not key_b64:
            logger.warning(
                "VENDOR_VAULT_KEY is not set — using a derived dev-only key. "
                "Do NOT use this in production."
            )
            self._key = hashlib.sha256(_DEV_KEY_SEED).digest()
        else:
            raw = base64.urlsafe_b64decode(key_b64.encode())
            if len(raw) != 32:
                raise ValueError(
                    "VENDOR_VAULT_KEY must decode to 32 bytes (run "
                    "generate_key() to create one)."
                )
            self._key = raw

    def encrypt(self, plaintext: str) -> str:
        """Encrypt ``plaintext`` → ``v1:<nonce>:<ciphertext>`` (all urlsafe-b64)."""
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._key)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return f"{_PREFIX}{base64.urlsafe_b64encode(nonce).decode()}:{base64.urlsafe_b64encode(ct).decode()}"

    def decrypt(self, token: str) -> str:
        """Decrypt a ``v1:`` envelope produced by :meth:`encrypt`."""
        if not token.startswith(_PREFIX):
            raise ValueError("Unrecognised vault token format (expected 'v1:').")
        _, nonce_b64, ct_b64 = token.split(":", 2)
        nonce = base64.urlsafe_b64decode(nonce_b64.encode())
        ct = base64.urlsafe_b64decode(ct_b64.encode())
        try:
            pt = AESGCM(self._key).decrypt(nonce, ct, None)
        except InvalidTag as exc:
            raise ValueError("Vault decryption failed (bad key or tampered token).") from exc
        return pt.decode("utf-8")


def generate_key() -> str:
    """Generate a fresh 32-byte urlsafe-base64 key suitable for ``VENDOR_VAULT_KEY``."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@lru_cache
def get_vault() -> Vault:
    """Return a cached :class:`Vault` built from ``VENDOR_VAULT_KEY`` (or dev fallback)."""
    return Vault(os.getenv("VENDOR_VAULT_KEY", ""))