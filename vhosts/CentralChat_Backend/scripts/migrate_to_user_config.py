"""M3 — Migrate legacy data to user-scoped tables.

Run once against a running Postgres + orchestrator.

Usage:
    python scripts/migrate_to_user_config.py [--db-url URL] [--dry-run]

Moves:
    config/cloud_models_allowlist.json → user_cloud_models (per-user)
    state/assistant_preferences.json   → user_preferences (per-user)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg  # type: ignore
except ImportError:
    print("psycopg is required. pip install psycopg[binary]")
    sys.exit(1)

DB_URL = os.environ.get("MEMORY_DB_URL", os.environ.get("DB_URL", ""))
CENTRAL_ROOT = os.environ.get("CENTRAL_ROOT", os.path.join(Path(__file__).resolve().parent.parent, ".central_root"))
DRY_RUN = "--dry-run" in sys.argv

# Override DB_URL from CLI
for i, arg in enumerate(sys.argv):
    if arg == "--db-url" and i + 1 < len(sys.argv):
        DB_URL = sys.argv[i + 1]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    if not DB_URL:
        print("Set MEMORY_DB_URL or pass --db-url URL")
        sys.exit(1)

    conn = psycopg.connect(DB_URL, autocommit=DRY_RUN)
    cur = conn.cursor()

    # Get all users
    cur.execute("SELECT id, email FROM auth_users WHERE active=true")
    users = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
    print(f"Found {len(users)} active users: {[e for _, e in users]}")

    # ── 1. Migrate cloud_models_allowlist.json ──
    allowlist_path = Path(CENTRAL_ROOT) / "config" / "cloud_models_allowlist.json"
    if allowlist_path.is_file():
        data = json.loads(allowlist_path.read_text())
        models = data.get("models", [])
        print(f"\nMigrating {len(models)} models from {allowlist_path}")

        for user_id, email in users:
            for m in models:
                if DRY_RUN:
                    print(f"  [DRY] INSERT user_cloud_models: user={email} model={m['id']}")
                    continue
                cur.execute(
                    """INSERT INTO user_cloud_models (user_id, model_id, label, enabled, version, source, updated_at)
                       VALUES (%s, %s, %s, true, 1, 'migration', %s)
                       ON CONFLICT (user_id, model_id) DO NOTHING""",
                    (user_id, m["id"], m.get("label", ""), now_iso()),
                )
            if not DRY_RUN:
                print(f"  Migrated {len(models)} models for {email}")
    else:
        print(f"\nNo cloud_models_allowlist.json at {allowlist_path} — skipping")

    # ── 2. Migrate assistant_preferences.json ──
    prefs_path = Path(CENTRAL_ROOT) / "state" / "assistant_preferences.json"
    if prefs_path.is_file():
        prefs = json.loads(prefs_path.read_text())
        print(f"\nMigrating preferences from {prefs_path}: {len(prefs)} keys")

        for user_id, email in users:
            for key, value in prefs.items():
                if DRY_RUN:
                    print(f"  [DRY] INSERT user_preferences: user={email} key={key}")
                    continue
                cur.execute(
                    """INSERT INTO user_preferences (user_id, key, value, version, source, updated_at)
                       VALUES (%s, %s, %s, 1, 'migration', %s)
                       ON CONFLICT (user_id, key) DO NOTHING""",
                    (user_id, key, json.dumps(value), now_iso()),
                )
            if not DRY_RUN:
                print(f"  Migrated {len(prefs)} preferences for {email}")
    else:
        print(f"\nNo assistant_preferences.json at {prefs_path} — skipping")

    if not DRY_RUN:
        conn.commit()
        print("\n✅ Migration complete.")
    else:
        print("\n🔍 Dry run complete. Remove --dry-run to execute.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
