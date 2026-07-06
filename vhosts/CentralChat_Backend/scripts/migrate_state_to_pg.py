#!/usr/bin/env python3
"""T9.3 — Migrate existing state files (JSON/JSONL) → Postgres.

Reads existing disk stores and writes them to the PG state tables.
Idempotent: skips already-migrated data.

Usage:
    python scripts/migrate_state_to_pg.py [--db-url URL] [--tenant-id default]
"""

import json
import os
import sys
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
ORCH_DIR = SCRIPT_DIR.parent

# Resolve DB URL
DB_URL = os.getenv("MEMORY_DB_URL", "")
TENANT_ID = "default"

for arg in sys.argv:
    if arg.startswith("--db-url="):
        DB_URL = arg.split("=", 1)[1]
    elif arg.startswith("--tenant-id="):
        TENANT_ID = arg.split("=", 1)[1]

if not DB_URL:
    env_path = ORCH_DIR / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("MEMORY_DB_URL="):
                DB_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if not DB_URL:
    print("ERROR: Set MEMORY_DB_URL or pass --db-url")
    sys.exit(1)

import psycopg

conn = psycopg.connect(DB_URL, autocommit=True)
cur = conn.cursor()

# Ensure tables
cur.execute(
    """CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'default',
        title TEXT DEFAULT 'Conversa', pinned BOOLEAN DEFAULT false,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());"""
)
cur.execute(
    """CREATE TABLE IF NOT EXISTS assistant_preferences (
        tenant_id TEXT PRIMARY KEY, prefs_json JSONB DEFAULT '{}',
        updated_at TIMESTAMPTZ DEFAULT now());"""
)

migrated = 0

# ── Migrate chat_sessions.json ──
state_dir = ORCH_DIR / "state"
if not state_dir.is_dir():
    state_dir = Path.home() / ".central" / "state"
chat_sessions_path = state_dir / "chat_sessions.json"
if chat_sessions_path.is_file():
    data = json.loads(chat_sessions_path.read_text(encoding="utf-8"))
    sessions = data.get("sessions", [])
    for s in sessions:
        if isinstance(s, dict):
            sid = str(s.get("id", ""))
            if len(sid) < 8:
                continue
            title = str(s.get("title", "Conversa"))[:120]
            pinned = bool(s.get("pinned", False))
            cur.execute(
                """INSERT INTO chat_sessions (id, tenant_id, title, pinned)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING;""",
                (sid, TENANT_ID, title, pinned),
            )
            msg_count = cur.rowcount
            migrated += msg_count
    print(f"chat_sessions.json: {len(sessions)} sessions, {migrated} migrated")

# ── Migrate preferences ──
prefs_path = state_dir / "assistant_preferences.json"
if not prefs_path.is_file():
    prefs_path = state_dir / "preferences.json"
if prefs_path.is_file():
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    cur.execute(
        """INSERT INTO assistant_preferences (tenant_id, prefs_json)
           VALUES (%s, %s::jsonb) ON CONFLICT (tenant_id) DO UPDATE SET
           prefs_json = EXCLUDED.prefs_json, updated_at = now();""",
        (TENANT_ID, json.dumps(prefs, ensure_ascii=False)),
    )
    print(f"preferences: {len(prefs)} keys migrated")

conn.close()
print("Migration complete.")
