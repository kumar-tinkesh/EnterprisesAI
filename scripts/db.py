"""Which database the app runs on, and switching it on purpose — never by itself.

    uv run python scripts/db.py status     # which one is active, and can it be reached
    uv run python scripts/db.py check      # exit 1 with what to do when the active one can't be reached
    uv run python scripts/db.py backup     # Supabase -> data/backup/supabase-<time>.db (a full SQLite copy)
    uv run python scripts/db.py local      # run on data/auth.db, refreshed from Supabase first when it can be
    uv run python scripts/db.py supabase   # run on Supabase again

(``make db-status``, ``make db-backup``, ``make db-local``, ``make db-supabase`` run these.)

``.env`` holds both URLs: ``SUPABASE_DATABASE_URL`` is where Supabase is;
``AUTH_DATABASE_URL`` is what docker compose actually uses — set means
Supabase, absent means the local SQLite file. Switching only edits that one
line, and the containers must be restarted to follow it.

Nothing is ever merged: what's created on one database stays there. So
``local`` first copies Supabase into data/auth.db (keeping the old file in
data/backup/), and ``supabase`` warns when the local file changed since —
those changes stay local.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parent.parent
ACTIVE, SUPABASE = "AUTH_DATABASE_URL", "SUPABASE_DATABASE_URL"
BATCH = 500


class Paths:
    def __init__(self, env: Path, data: Path):
        self.env, self.data = env, data
        self.db = data / "auth.db"
        self.backup = data / "backup"
        self.mode = data / ".db-mode"  # {"mode": "local"|"supabase", "since": iso, "db_sha256": the local file's when switched}


# ── .env, without ever printing a password ──

def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


def set_env(path: Path, key: str, value: str | None) -> None:
    """Set (or, with None, remove) one ``KEY=`` line; every other line stays as it is."""
    lines = path.read_text().splitlines() if path.exists() else []
    kept = [l for l in lines if not re.match(rf"^\s*{key}\s*=", l)]
    if value is not None:
        quoted = f"'{value}'" if "$" in value else value  # compose would read "$" as a variable
        kept.append(f"{key}={quoted}")
    path.write_text("\n".join(kept) + "\n")


def where(url: str) -> str:
    """A URL without its password: "Supabase (aws-0-ap-south-1.pooler.supabase.com)" or the SQLite file."""
    if url.startswith("sqlite"):
        return f"local SQLite ({url.split(':///', 1)[-1]})"
    host = re.sub(r"^.*@", "", url).split("/")[0].split(":")[0]
    return f"{'Supabase' if 'supabase' in host else 'Postgres'} ({host})"


def project_ref(url: str) -> str | None:
    m = re.search(r"postgres\.([a-z0-9]+):", url)
    return m.group(1) if m else None


# ── reaching it ──

async def reach(url: str, seconds: float = 10) -> str | None:
    """None when it answers; else why not, in a few words."""
    engine = create_async_engine(url, connect_args={"timeout": seconds} if url.startswith("postgresql") else {})
    try:
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("select 1")), seconds)
        return None
    except Exception as exc:  # noqa: BLE001 — any failure means "can't use it now"
        return (str(exc).splitlines() or [type(exc).__name__])[0].replace(url, "<url>")[:200]
    finally:
        await engine.dispose()


def unreachable_help(url: str, why: str) -> str:
    ref = project_ref(url)
    paused = "tenant or user not found" in why.lower()
    return "\n".join([
        f"✗ Couldn't reach the database: {where(url)}",
        f"  Reason: {why}",
        "",
        "  What to do:",
        "  • The free Supabase plan pauses a project after 7 days without use"
        + (" (this looks like that)." if paused else "."),
        f"    Open https://supabase.com/dashboard/project/{ref} and press \"Restore project\"." if ref else "    Restore it from the Supabase dashboard.",
        "  • No internet? Check the connection and try again.",
        "  • To work on the local database instead:  make db-local",
        "",
        "  Nothing was started, so nothing was written anywhere.",
    ])


# ── copying Supabase into a SQLite file ──

def migrate(url: str) -> None:
    done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                          env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True)
    if done.returncode:
        sys.exit("Couldn't build the tables:\n" + done.stderr[-3000:])


async def snapshot(url: str, out: Path) -> dict[str, int]:
    """Every row of ``url`` into a new SQLite file at ``out`` (built on the same migrations); counts per table."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    migrate(f"sqlite+aiosqlite:///{partial}")
    src, dst = create_async_engine(url), create_async_engine(f"sqlite+aiosqlite:///{partial}")
    src_meta, dst_meta = MetaData(), MetaData()
    counts: dict[str, int] = {}
    try:
        async with src.connect() as s, dst.begin() as d:
            await s.run_sync(src_meta.reflect)
            await d.run_sync(dst_meta.reflect)
            v_src = (await s.execute(text("select version_num from alembic_version"))).scalar()
            v_dst = (await d.execute(text("select version_num from alembic_version"))).scalar()
            if v_src != v_dst:
                raise SystemExit(f"Supabase is at migration {v_src}, this code at {v_dst}: start the app on Supabase once, then retry.")
            for t in dst_meta.sorted_tables:
                if t.name == "alembic_version" or t.name not in src_meta.tables:
                    continue
                rows = (await s.execute(select(src_meta.tables[t.name]))).mappings().all()
                cols = [c for c in t.columns.keys() if c in src_meta.tables[t.name].columns]
                for start in range(0, len(rows), BATCH):
                    await d.execute(t.insert(), [{c: r[c] for c in cols} for r in rows[start:start + BATCH]])
                counts[t.name] = len(rows)
            for name, n in counts.items():
                got = (await d.execute(select(func.count()).select_from(dst_meta.tables[name]))).scalar_one()
                if got != n:
                    raise SystemExit(f"Counts differ on {name}: Supabase {n}, copy {got} — the copy was thrown away.")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        await src.dispose()
        await dst.dispose()
    partial.rename(out)
    return counts


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"{question} — run again with YES=1 to go ahead.")
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def fingerprint(path: Path) -> str | None:
    """The file's SHA-256: any change to the local database changes it."""
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_mode(p: Paths, mode: str) -> None:
    p.mode.write_text(json.dumps({"mode": mode, "since": datetime.now().isoformat(timespec="seconds"), "db_sha256": fingerprint(p.db)}))


# ── commands ──

async def cmd_status(p: Paths, _args) -> int:
    env = read_env(p.env)
    active = env.get(ACTIVE)
    print(f"Active:   {where(active) if active else 'local SQLite (data/auth.db)'}")
    if env.get(SUPABASE):
        why = await reach(env[SUPABASE])
        print(f"Supabase: {'reachable' if why is None else 'NOT reachable — ' + why}")
    else:
        print(f"Supabase: not set up ({SUPABASE} isn't in .env)")
    if p.db.exists():
        print(f"Local:    data/auth.db, last changed {datetime.fromtimestamp(p.db.stat().st_mtime):%d %b %Y %H:%M}")
    return 0


async def cmd_check(p: Paths, _args) -> int:
    url = read_env(p.env).get(ACTIVE)
    if not url:
        return 0  # local SQLite: the file is created and migrated on start
    why = await reach(url)
    if why is None:
        return 0
    print(unreachable_help(url, why))
    return 1


async def cmd_backup(p: Paths, _args) -> int:
    url = read_env(p.env).get(SUPABASE)
    if not url:
        print(f"{SUPABASE} isn't in .env: nothing to back up.")
        return 1
    why = await reach(url)
    if why:
        print(unreachable_help(url, why))
        return 1
    out = p.backup / f"supabase-{stamp()}.db"
    counts = await snapshot(url, out)
    print(f"✓ Copied {sum(counts.values())} rows in {len(counts)} tables to {out.relative_to(p.data.parent)}")
    return 0


async def cmd_local(p: Paths, args) -> int:
    env = read_env(p.env)
    if not env.get(ACTIVE):
        print("Already on the local database (data/auth.db).")
        return 0
    url = env.get(SUPABASE) or env[ACTIVE]
    why = await reach(url)
    if why is None:
        print(f"Copying Supabase into the local database first, so it has everything…")
        fresh = p.backup / f"supabase-{stamp()}.db"
        counts = await snapshot(url, fresh)
        if p.db.exists():
            kept = p.backup / f"auth-before-local-{stamp()}.db"
            shutil.copy2(p.db, kept)
            print(f"  the old data/auth.db is kept as {kept.relative_to(p.data.parent)}")
        shutil.copy2(fresh, p.db)
        print(f"  ✓ data/auth.db now holds {sum(counts.values())} rows copied from Supabase")
    else:
        when = f"{datetime.fromtimestamp(p.db.stat().st_mtime):%d %b %Y %H:%M}" if p.db.exists() else "never"
        print(f"Supabase can't be reached ({why}), so data/auth.db can't be refreshed.")
        print(f"It was last changed {when}: anything newer that's only in Supabase won't be there.")
        if not confirm("Switch to the local database anyway?", args.yes):
            print("Nothing changed.")
            return 1
    set_env(p.env, ACTIVE, None)
    write_mode(p, "local")
    print("✓ Switched to the local database. Restart to use it:  make docker-down && make docker-dev")
    print("  Back to Supabase later:  make db-supabase  (what you create locally stays local)")
    return 0


async def cmd_supabase(p: Paths, args) -> int:
    env = read_env(p.env)
    url = env.get(SUPABASE)
    if not url:
        print(f"Put the Supabase URL in .env as {SUPABASE}=postgresql+asyncpg://… first.")
        return 1
    if env.get(ACTIVE) == url:
        print("Already on Supabase.")
        return 0
    why = await reach(url)
    if why:
        print(unreachable_help(url, why))
        return 1
    # Work done on the local database since switching to it isn't in Supabase.
    try:
        mode = json.loads(p.mode.read_text())
    except (OSError, ValueError):
        mode = {}
    if mode.get("mode") == "local" and p.db.exists() and fingerprint(p.db) != mode.get("db_sha256"):
        kept = p.backup / f"local-changes-{stamp()}.db"
        shutil.copy2(p.db, kept)
        print(f"The local database changed since {mode.get('since', 'the switch')}: those changes are NOT in Supabase.")
        print(f"They stay in data/auth.db (and a copy: {kept.relative_to(p.data.parent)}).")
        if not confirm("Switch to Supabase anyway?", args.yes):
            print("Nothing changed.")
            return 1
    set_env(p.env, ACTIVE, url)
    write_mode(p, "supabase")
    print(f"✓ Switched to {where(url)}. Restart to use it:  make docker-down && make docker-dev")
    return 0


COMMANDS = {"status": cmd_status, "check": cmd_check, "backup": cmd_backup, "local": cmd_local, "supabase": cmd_supabase}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--yes", action="store_true", default=os.environ.get("YES") == "1", help="don't ask before switching")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    sys.exit(asyncio.run(COMMANDS[args.command](Paths(args.env_file, args.data_dir), args)))


if __name__ == "__main__":
    main()
