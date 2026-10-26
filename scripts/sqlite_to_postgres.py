"""Copy every row of the SQLite database into an empty Postgres database (e.g. Supabase).

    TARGET_DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST:5432/postgres?ssl=require' \\
        uv run python scripts/sqlite_to_postgres.py [--sqlite data/auth.db] [--check]

What it does, in order — and it stops before writing anything if a check fails:
1. Copies the SQLite file to a temporary file and brings THAT copy to the latest
   migration (the original is only ever read, never changed).
2. Brings the target's schema to the latest migration (``alembic upgrade head``),
   the same chain the app runs on start.
3. Refuses if the target already holds data (nothing is ever overwritten), or if
   any SQLite column has no place in the target (that would be data lost).
4. Copies every table in one transaction, converting SQLite's text dates, 0/1
   booleans and JSON text to real Postgres values. Any error rolls it all back.
   Rows SQLite kept although what they point to was deleted (it never checked;
   Postgres refuses them) are not copied: they're written to a JSON file beside
   the backups and listed, so nothing disappears unseen.
5. Moves id counters past the copied rows, then counts every table on both sides
   and fails loudly if any differ.

``--check`` does steps 1–3 and a dry run of 4 (rolled back): see what would happen.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, MetaData, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine

SKIP = {"alembic_version"}  # written by the migrations themselves
BATCH = 500


def _datetime(value, aware: bool):
    if isinstance(value, (int, float)):
        out = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if aware and out.tzinfo is None:
        return out.replace(tzinfo=timezone.utc)  # SQLite keeps UTC without a zone
    if not aware and out.tzinfo is not None:
        return out.astimezone(timezone.utc).replace(tzinfo=None)
    return out


def converter(column):
    """SQLite value -> what asyncpg wants for this target column."""
    kind = column.type
    if isinstance(kind, Boolean):
        return lambda v: None if v is None else bool(v)
    if isinstance(kind, (JSON, JSONB)):
        return lambda v: json.loads(v) if isinstance(v, (str, bytes)) else v
    if isinstance(kind, DateTime):
        aware = bool(getattr(kind, "timezone", False))
        return lambda v: None if v in (None, "") else _datetime(v, aware)
    if isinstance(kind, Date):
        return lambda v: None if v in (None, "") else (v if isinstance(v, date) else date.fromisoformat(str(v)[:10]))
    return lambda v: v


def migrate_schema(url: str, what: str) -> None:
    print(f"     Bringing {what} to the latest migration (alembic upgrade head)…")
    env = {**os.environ, "DATABASE_URL": url}
    done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout[-2000:], done.stderr[-4000:], sep="\n")
        sys.exit(f"Couldn't bring {what} to the latest migration — nothing was copied.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default="data/auth.db", help="the SQLite file to copy from (opened read-only)")
    parser.add_argument("--check", action="store_true", help="dry run: everything except keeping the copy")
    parser.add_argument("--orphans", default=None, help="where to write rows that point to deleted records (default: data/backup/skipped-rows-<time>.json)")
    args = parser.parse_args()

    url = os.environ.get("TARGET_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        sys.exit("Set TARGET_DATABASE_URL to the Postgres URL, starting postgresql+asyncpg://")
    if not os.path.exists(args.sqlite):
        sys.exit(f"No SQLite file at {args.sqlite}")

    # Read from an up-to-date copy, so both sides are on the same migration; the original stays as it is.
    print(f"1/4  Preparing a copy of {args.sqlite} (the original is not changed)…")
    workdir = tempfile.mkdtemp(prefix="sqlite-to-pg-")
    copy = os.path.join(workdir, "source.db")
    original = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    snapshot = sqlite3.connect(copy)
    original.backup(snapshot)
    snapshot.close()
    original.close()
    migrate_schema(f"sqlite+aiosqlite:///{copy}", "the copy")
    source = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source_tables = {r[0] for r in source.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
    (version,) = source.execute("select version_num from alembic_version").fetchone()
    print(f"     Source: {args.sqlite} (migration {version}, {len(source_tables)} tables)")

    migrate_schema(url, "the target")
    engine = create_async_engine(url)
    meta = MetaData()
    async with engine.connect() as conn:
        await conn.run_sync(meta.reflect)
        (target_version,) = (await conn.execute(text("select version_num from alembic_version"))).one()
    if target_version != version:
        sys.exit(f"The target is at migration {target_version}, the SQLite file at {version}. Start the app once on SQLite "
                 "so both are on the same version, then run this again.")

    tables = [t for t in meta.sorted_tables if t.name not in SKIP]
    print("2/4  Checking nothing would be overwritten or left behind…")
    problems = []
    async with engine.connect() as conn:
        for t in tables:
            if (await conn.execute(select(func.count()).select_from(t))).scalar_one():
                problems.append(f"target table {t.name} already has rows")
    for name in sorted(source_tables - SKIP):
        if name not in meta.tables:
            if source.execute(f'select count(*) from "{name}"').fetchone()[0]:
                problems.append(f"table {name} has rows but no place in the target")
            continue
        target_cols = set(meta.tables[name].columns.keys())
        for col in (r[1] for r in source.execute(f'pragma table_info("{name}")')):
            if col not in target_cols:
                problems.append(f"column {name}.{col} has no place in the target")
    if problems:
        print("\n".join(f"  ✗ {p}" for p in problems))
        sys.exit("Stopped before copying anything.")

    print("3/4  Copying" + (" (dry run — rolled back at the end)" if args.check else "") + "…")
    counts: dict[str, int] = {}
    # Rows already copied, by table and column: what a foreign key may point to.
    present: dict[tuple[str, str], set] = {}
    skipped: dict[str, list[dict]] = {}
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            for t in tables:
                if t.name not in source_tables:
                    continue
                cols = [r[1] for r in source.execute(f'pragma table_info("{t.name}")')]
                convert = {c: converter(t.columns[c]) for c in cols}
                all_rows = source.execute(f'select {", ".join(f"[{c}]" for c in cols)} from "{t.name}"').fetchall()
                # A row pointing to a record that no longer exists can't go into Postgres: set it aside.
                links = [(fk.parent.name, fk.column.table.name, fk.column.name) for fk in t.foreign_keys if fk.parent.name in cols]
                for _, ref_table, ref_col in links:
                    if ref_table == t.name:  # pointing within the same table: any of its rows will do
                        present.setdefault((ref_table, ref_col), set()).update(r[ref_col] for r in all_rows)
                rows, orphans = [], []
                for r in all_rows:
                    ok = all(r[c] is None or r[c] in present.get((rt, rc), set()) for c, rt, rc in links)
                    (rows if ok else orphans).append(r)
                if orphans:
                    skipped[t.name] = [dict(r) for r in orphans]
                for col in cols:
                    present.setdefault((t.name, col), set()).update(r[col] for r in rows)
                for start in range(0, len(rows), BATCH):
                    batch = [{c: convert[c](row[c]) for c in cols} for row in rows[start:start + BATCH]]
                    await conn.execute(t.insert(), batch)
                counts[t.name] = len(rows)
                if all_rows:
                    print(f"     {t.name}: {len(rows)}" + (f"  (+{len(orphans)} pointing to deleted records, set aside)" if orphans else ""))
            # Integer ids handed out by the database: carry on after the copied ones.
            for t in tables:
                for c in t.primary_key.columns:
                    seq = (await conn.execute(text("select pg_get_serial_sequence(:t, :c)"), {"t": t.name, "c": c.name})).scalar()
                    if seq:
                        await conn.execute(text(f'select setval(:s, coalesce((select max("{c.name}") from "{t.name}"), 0) + 1, false)'), {"s": seq})
            print("4/4  Counting both sides…")
            wrong = []
            for name, n in counts.items():
                got = (await conn.execute(select(func.count()).select_from(meta.tables[name]))).scalar_one()
                total = source.execute(f'select count(*) from "{name}"').fetchone()[0]
                if got != n or n + len(skipped.get(name, [])) != total:
                    wrong.append(f"{name}: SQLite {n}, Postgres {got}")
            if wrong:
                raise RuntimeError("Counts differ: " + "; ".join(wrong))
            set_aside = sum(len(v) for v in skipped.values())
            if args.check:
                await trans.rollback()
                print(f"Dry run OK: {sum(counts.values())} rows in {len(counts)} tables would be copied"
                      + (f"; {set_aside} rows pointing to deleted records would be set aside" if set_aside else "") + ". Nothing was kept.")
            else:
                await trans.commit()
                print(f"Done: {sum(counts.values())} rows in {len(counts)} tables copied, every count matches.")
            if skipped and not args.check:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                path = args.orphans or os.path.join(os.path.dirname(os.path.abspath(args.sqlite)), "backup", f"skipped-rows-{stamp}.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(skipped, f, indent=2, default=str)
                print(f"     {set_aside} rows pointing to deleted records are kept in {path}")
        except BaseException:
            await trans.rollback()
            print("Rolled back — the target has no copied rows.")
            raise
    await engine.dispose()
    source.close()
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
