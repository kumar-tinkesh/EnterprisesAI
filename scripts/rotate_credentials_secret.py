"""Re-encrypt every stored app login (MCP credentials) and WhatsApp bridge token under a new secret.

    uv run python scripts/rotate_credentials_secret.py [--check]

Why: they're Fernet-encrypted with a key derived from ``MCP_CREDENTIALS_SECRET``,
or ``JWT_PRIVATE_KEY`` when that's empty — and when both are empty, from an empty
string, which anyone holding the database can reproduce.

Stop the app first (it reads the secret when it starts) and start it again after.

What it does — and it changes nothing if any check fails:
1. Finds the databases: the active one (``AUTH_DATABASE_URL``, else the local
   ``data/auth.db``) and, if that's Supabase, ``data/auth.db`` too — so
   ``make db-local`` keeps working with the same secret.
2. Opens every value with the secret the app uses now. If one doesn't open: stop.
3. The new secret: ``MCP_CREDENTIALS_SECRET_PENDING`` from ``.env`` when an earlier
   run stopped half way, else a new random one — written to ``.env`` (as that
   PENDING line) BEFORE any database changes, so it can't be lost.
4. Per database, one transaction: encrypt each value with the new secret, read
   it back, open it with the new secret and compare with the original; then commit.
   A database already on the new secret (an earlier run got that far) is left as is.
5. ``.env``: ``MCP_CREDENTIALS_SECRET=<new>``; the PENDING line goes.

``--check`` does 1–2 and says what would change, without touching anything.
Backups made before (data/backup/*.db) keep the old encryption.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import secrets
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
LOCAL = f"sqlite+aiosqlite:///{ROOT / 'data' / 'auth.db'}"
PENDING = "MCP_CREDENTIALS_SECRET_PENDING"
# (table, id column, encrypted column): everything that's encrypted this way.
COLUMNS = [
    ("vendor_mcp_credentials", "id", "encrypted_credentials"),
    ("vendor_mcp_bridge_instances", "id", "token_encrypted"),
]


def fernet(secret: str) -> Fernet:
    """The app's own derivation (vendor/services/mcp_auth/crypto.py, auth's McpCredentialManager)."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"mcp_credentials_salt", iterations=100_000)
    return Fernet(urlsafe_b64encode(kdf.derive(secret.encode())))


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


def set_env(key: str, value: str | None) -> None:
    lines = [l for l in ENV.read_text().splitlines() if not re.match(rf"^\s*{key}\s*=", l)]
    if value is not None:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")


def where(url: str) -> str:
    return "data/auth.db" if url.startswith("sqlite") else "Supabase (" + re.sub(r"^.*@", "", url).split("/")[0].split(":")[0] + ")"


async def read_values(url: str) -> list[tuple[str, str, str, str]]:
    """(table, id column, id, encrypted value) for every stored value."""
    engine = create_async_engine(url)
    out = []
    try:
        async with engine.connect() as conn:
            for table, key, col in COLUMNS:
                rows = (await conn.execute(text(f'select "{key}", "{col}" from "{table}" where "{col}" is not null'))).all()
                out += [(table, key, r[0], r[1]) for r in rows]
    finally:
        await engine.dispose()
    return out


def opens_with(f: Fernet, values) -> list | None:
    """The plaintexts when every value opens with ``f``, else None."""
    try:
        return [f.decrypt(v.encode()) for *_, v in values]
    except InvalidToken:
        return None


async def rotate(url: str, old: Fernet, new: Fernet) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            values = []
            for table, key, col in COLUMNS:
                rows = (await conn.execute(text(f'select "{key}", "{col}" from "{table}" where "{col}" is not null'))).all()
                values += [(table, key, col, r[0], r[1]) for r in rows]
            for table, key, col, rid, enc in values:
                plain = old.decrypt(enc.encode())
                await conn.execute(text(f'update "{table}" set "{col}" = :v where "{key}" = :id'), {"v": new.encrypt(plain).decode(), "id": rid})
            # Read every one back and open it with the new secret before committing.
            for table, key, col, rid, enc in values:
                back = (await conn.execute(text(f'select "{col}" from "{table}" where "{key}" = :id'), {"id": rid})).scalar_one()
                if new.decrypt(back.encode()) != old.decrypt(enc.encode()):
                    raise SystemExit(f"{table} {rid}: didn't read back the same — rolled back, nothing changed.")
        return len(values)
    finally:
        await engine.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only say what would change")
    args = parser.parse_args()

    env = read_env()
    active = env.get("AUTH_DATABASE_URL") or LOCAL
    targets = [active] + ([LOCAL] if active != LOCAL and (ROOT / "data" / "auth.db").exists() else [])
    current = fernet(env.get("MCP_CREDENTIALS_SECRET") or env.get("JWT_PRIVATE_KEY") or "")
    pending = env.get(PENDING)
    if env.get("MCP_CREDENTIALS_SECRET") and not pending:
        print("MCP_CREDENTIALS_SECRET is already set. To rotate it again, remove it only after re-encrypting — not handled here.")
        return

    plan = []
    for url in targets:
        values = await read_values(url)
        if opens_with(current, values) is not None:
            state = "current"
        elif pending and opens_with(fernet(pending), values) is not None:
            state = "done"  # an earlier run already moved this one
        else:
            sys.exit(f"Some values in {where(url)} don't open with the secret the app uses now — stopped, nothing changed.")
        plan.append((url, len(values), state))
        print(f"{where(url)}: {len(values)} encrypted values — " + ("all open with the current secret" if state == "current" else "already on the new secret"))

    if args.check:
        print("Check only: nothing changed.")
        return

    new_secret = pending or secrets.token_urlsafe(48)
    if not pending:
        set_env(PENDING, new_secret)  # saved before any database changes
    new = fernet(new_secret)
    for url, n, state in plan:
        if state == "done":
            continue
        done = await rotate(url, current, new)
        print(f"✓ {where(url)}: {done} values re-encrypted and read back")
    for url, *_ in plan:
        if opens_with(new, await read_values(url)) is None:
            sys.exit(f"{where(url)} doesn't fully open with the new secret — .env keeps {PENDING}; run this again.")
    set_env("MCP_CREDENTIALS_SECRET", new_secret)
    set_env(PENDING, None)
    print("✓ .env: MCP_CREDENTIALS_SECRET set (keep .env safe — without it the logins can't be opened). Restart the app.")


if __name__ == "__main__":
    asyncio.run(main())
