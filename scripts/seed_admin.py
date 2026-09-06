#!/usr/bin/env python3
"""Seed (or reset) the platform admin account (VendorUser / role=vendor_admin).

There is no self-signup UI for this role by design (tenant_admin/tenant_user
signup is likewise disabled) so a fresh database has no way to log into the
vendor dashboard until one is created here.

Connects through the auth service's own Settings/.env, so it targets whatever
DATABASE_URL is active in your environment -- the same SQLite file the `auth`
container uses by default (./data/auth.db), or Postgres if configured.

Usage:
    uv run python scripts/seed_admin.py --email admin@example.com --password "change-me-now"
    uv run python scripts/seed_admin.py --email admin@example.com --password "..." --force  # reset password

Env var fallbacks (used when the matching flag is omitted):
    SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD, SEED_ADMIN_NAME
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_APP_DIR = REPO_ROOT / "apps" / "auth"

# Match how Settings() resolves ".env" (relative to cwd) and how the auth
# service's own modules are imported (relative to apps/auth), regardless of
# the directory this script is invoked from.
os.chdir(REPO_ROOT)
sys.path.insert(0, str(AUTH_APP_DIR))

from sqlalchemy import select  # noqa: E402

from src.core.roles import Roles  # noqa: E402
from src.core.security import hash_password  # noqa: E402
from src.db.session import SessionLocal, create_db_tables  # noqa: E402
from src.models import VendorUser  # noqa: E402


async def seed_admin(email: str, password: str, full_name: str, *, force: bool) -> None:
    email = email.strip().lower()

    # No-op if migrations already created the schema; fills it in otherwise
    # (e.g. a brand-new SQLite file with no alembic history yet).
    await create_db_tables()

    async with SessionLocal() as db:
        existing = (
            await db.execute(select(VendorUser).where(VendorUser.email == email))
        ).scalars().first()

        if existing and not force:
            print(
                f"[seed_admin] '{email}' already exists (id={existing.id}). "
                "Pass --force to reset its password."
            )
            return

        if existing:
            existing.hashed_password = hash_password(password)
            existing.full_name = full_name or existing.full_name
            existing.is_active = True
            action = "Updated"
        else:
            existing = VendorUser(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=Roles.VENDOR_ADMIN,
                is_active=True,
            )
            db.add(existing)
            action = "Created"

        await db.commit()
        await db.refresh(existing)
        print(f"[seed_admin] {action} platform admin '{email}' (id={existing.id}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", default=os.environ.get("SEED_ADMIN_EMAIL", "admin@enterpriseai.local")
    )
    parser.add_argument("--password", default=os.environ.get("SEED_ADMIN_PASSWORD"))
    parser.add_argument(
        "--name", default=os.environ.get("SEED_ADMIN_NAME", "Platform Admin")
    )
    parser.add_argument(
        "--force", action="store_true", help="Reset the password if the account already exists."
    )
    args = parser.parse_args()

    if not args.password:
        parser.error("--password is required (or set SEED_ADMIN_PASSWORD)")
    if len(args.password) < 8:
        parser.error("--password must be at least 8 characters")

    asyncio.run(seed_admin(args.email, args.password, args.name, force=args.force))


if __name__ == "__main__":
    main()
