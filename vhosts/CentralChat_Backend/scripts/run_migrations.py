#!/usr/bin/env python3
"""T5.5 — Migration runner: executes raw SQL files in order.

Usage:
    python scripts/run_migrations.py [--db-url URL] [--dry-run]

Reads migrations/*.sql files, sorts by filename, executes each one
that hasn't been recorded in the _migrations table.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

# Stable advisory lock id for concurrent migrate jobs (compose / helm).
_MIGRATION_LOCK_KEY = 0x436E7472616C4D47  # "CentralMG"

# Resolve DB URL
DB_URL = os.getenv("MEMORY_DB_URL", "")
for arg in sys.argv:
    if arg.startswith("--db-url="):
        DB_URL = arg.split("=", 1)[1]
    elif arg == "--db-url" and sys.argv.index(arg) + 1 < len(sys.argv):
        DB_URL = sys.argv[sys.argv.index(arg) + 1]

if not DB_URL:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("MEMORY_DB_URL="):
                DB_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if not DB_URL:
    print("ERROR: No database URL. Set MEMORY_DB_URL or pass --db-url.")
    sys.exit(1)

try:
    import psycopg
except ImportError:
    print("ERROR: psycopg not installed.")
    sys.exit(1)

migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
files = sorted(f for f in migrations_dir.glob("*.sql") if f.name[0].isdigit())

if not files:
    print(f"ERROR: No migration files found in {migrations_dir}/")
    sys.exit(1)

conn = psycopg.connect(DB_URL, autocommit=True)
cur = conn.cursor()

cur.execute(
    """CREATE TABLE IF NOT EXISTS _migrations (
        filename TEXT PRIMARY KEY,
        executed_at TIMESTAMPTZ NOT NULL DEFAULT now());"""
)

cur.execute("SELECT pg_advisory_lock(%s);", (_MIGRATION_LOCK_KEY,))

try:
    cur.execute("SELECT filename FROM _migrations;")
    executed = {r[0] for r in cur.fetchall()}
    pending = [f for f in files if f.name not in executed]

    if not pending:
        print(f"All {len(files)} migrations already applied.")
        sys.exit(0)

    print(f"Pending: {len(pending)}/{len(files)} migrations")
    if DRY_RUN:
        for f in pending:
            print(f"  [DRY-RUN] {f.name}")
        sys.exit(0)

    for mf in pending:
        print(f"  Applying: {mf.name} ...", end=" ")
        sql = mf.read_text(encoding="utf-8")
        try:
            cur.execute(sql)
            cur.execute("INSERT INTO _migrations (filename) VALUES (%s);", (mf.name,))
            print("OK")
        except Exception as exc:
            print(f"FAILED: {exc}")
            sys.exit(1)

    print(f"Done. {len(pending)} migrations applied.")
finally:
    cur.execute("SELECT pg_advisory_unlock(%s);", (_MIGRATION_LOCK_KEY,))
    conn.close()
