#!/usr/bin/env python3
"""T10 — Session Retention Worker: cleanup old sessions, events, and jobs.

Usage:
    python scripts/retention_worker.py [--db-url URL] [--dry-run] [--once]

Config via env vars:
    CENTRAL_RETENTION_SESSION_DAYS (default 90)  — chat sessions without activity
    CENTRAL_RETENTION_EVENT_DAYS   (default 30)  — session event log
    CENTRAL_RETENTION_JOB_DAYS     (default 7)   — completed/failed embedding jobs
    CENTRAL_RETENTION_ENABLED      (default 1)

Without --once, sleeps and retries periodically (cron-friendly wrapper mode).
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ──
DB_URL = os.getenv("MEMORY_DB_URL", "")
SESSION_DAYS = int(os.getenv("CENTRAL_RETENTION_SESSION_DAYS", "90") or "90")
EVENT_DAYS = int(os.getenv("CENTRAL_RETENTION_EVENT_DAYS", "30") or "30")
JOB_DAYS = int(os.getenv("CENTRAL_RETENTION_JOB_DAYS", "7") or "7")
ENABLED = os.getenv("CENTRAL_RETENTION_ENABLED", "1").strip().lower() in ("1", "true", "yes")
DRY_RUN = "--dry-run" in sys.argv
ONCE = "--once" in sys.argv

for arg in sys.argv:
    if arg.startswith("--db-url="):
        DB_URL = arg.split("=", 1)[1]

if not DB_URL:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("MEMORY_DB_URL="):
                DB_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if not DB_URL:
    print("ERROR: Set MEMORY_DB_URL or pass --db-url", file=sys.stderr)
    sys.exit(1)

if not ENABLED:
    print("[retention_worker] Disabled (CENTRAL_RETENTION_ENABLED=0)")
    sys.exit(0)

import psycopg

# ── Thresholds ──
now = datetime.now(timezone.utc)


def _run_cleanup() -> dict[str, int]:
    """Execute cleanup and return deletion counts."""
    conn = psycopg.connect(DB_URL, autocommit=True)
    cur = conn.cursor()
    counts: dict[str, int] = {}

    # Session events
    event_cutoff = now - timedelta(days=EVENT_DAYS)
    cur.execute(
        "SELECT COUNT(*) FROM session_events WHERE created_at < %s;",
        (event_cutoff,),
    )
    counts["session_events_total"] = int(cur.fetchone()[0] or 0)
    if not DRY_RUN:
        cur.execute("DELETE FROM session_events WHERE created_at < %s;", (event_cutoff,))
        counts["session_events_deleted"] = int(cur.rowcount or 0)
    else:
        counts["session_events_deleted"] = 0
        print(f"  [DRY-RUN] session_events: {counts['session_events_total']} would be deleted")

    # Chat sessions (no activity)
    session_cutoff = now - timedelta(days=SESSION_DAYS)
    cur.execute(
        "SELECT COUNT(*) FROM chat_sessions WHERE updated_at < %s AND pinned = false;",
        (session_cutoff,),
    )
    counts["chat_sessions_total"] = int(cur.fetchone()[0] or 0)
    if not DRY_RUN:
        cur.execute(
            "DELETE FROM chat_sessions WHERE updated_at < %s AND pinned = false;",
            (session_cutoff,),
        )
        counts["chat_sessions_deleted"] = int(cur.rowcount or 0)
    else:
        counts["chat_sessions_deleted"] = 0
        print(f"  [DRY-RUN] chat_sessions: {counts['chat_sessions_total']} would be deleted")

    # Embedding jobs (completed/failed)
    job_cutoff = now - timedelta(days=JOB_DAYS)
    cur.execute(
        "SELECT COUNT(*) FROM embedding_jobs WHERE status IN ('done', 'failed') AND completed_at < %s;",
        (job_cutoff,),
    )
    counts["embedding_jobs_total"] = int(cur.fetchone()[0] or 0)
    if not DRY_RUN:
        cur.execute(
            "DELETE FROM embedding_jobs WHERE status IN ('done', 'failed') AND completed_at < %s;",
            (job_cutoff,),
        )
        counts["embedding_jobs_deleted"] = int(cur.rowcount or 0)
    else:
        counts["embedding_jobs_deleted"] = 0
        print(f"  [DRY-RUN] embedding_jobs: {counts['embedding_jobs_total']} would be deleted")

    # Workspace sessions (respect existing TTL via expires_at)
    cur.execute(
        "SELECT COUNT(*) FROM workspace_sessions WHERE expires_at < now();"
    )
    counts["workspace_expired"] = int(cur.fetchone()[0] or 0)
    if not DRY_RUN:
        cur.execute("DELETE FROM workspace_sessions WHERE expires_at < now();")
        counts["workspace_deleted"] = int(cur.rowcount or 0)
    else:
        counts["workspace_deleted"] = 0
        print(f"  [DRY-RUN] workspace_sessions: {counts['workspace_expired']} would be deleted")

    audit_days = int(os.getenv("CENTRAL_AUDIT_RETENTION_DAYS", "365") or "365")
    audit_cutoff = now - timedelta(days=audit_days)
    cur.execute("SELECT COUNT(*) FROM audit_events WHERE created_at < %s;", (audit_cutoff,))
    counts["audit_events_total"] = int(cur.fetchone()[0] or 0)
    if not DRY_RUN:
        cur.execute("DELETE FROM audit_events WHERE created_at < %s;", (audit_cutoff,))
        counts["audit_events_deleted"] = int(cur.rowcount or 0)
    else:
        counts["audit_events_deleted"] = 0
        print(f"  [DRY-RUN] audit_events: {counts['audit_events_total']} would be deleted")

    conn.close()
    return counts


# ── Run ──
ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"[retention_worker] {ts} DRY_RUN={DRY_RUN}", flush=True)

counts = _run_cleanup()

total = sum(
    counts.get(k, 0)
    for k in (
        "session_events_deleted",
        "chat_sessions_deleted",
        "embedding_jobs_deleted",
        "workspace_deleted",
        "audit_events_deleted",
    )
)
print(
    f"[retention_worker] Done: {total} total deleted "
    f"(events={counts.get('session_events_deleted', 0)}, "
    f"sessions={counts.get('chat_sessions_deleted', 0)}, "
    f"jobs={counts.get('embedding_jobs_deleted', 0)}, "
    f"workspace={counts.get('workspace_deleted', 0)}, "
    f"audit={counts.get('audit_events_deleted', 0)})",
    flush=True,
)

if ONCE:
    sys.exit(0)

# ── Periodic mode ──
INTERVAL = 3600  # 1 hour
print(f"[retention_worker] Sleeping {INTERVAL}s until next run...", flush=True)
while True:
    try:
        time.sleep(INTERVAL)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[retention_worker] {ts} periodic run", flush=True)
        counts = _run_cleanup()
        print(f"[retention_worker] Done: {sum(counts.values())} affected", flush=True)
    except KeyboardInterrupt:
        print("[retention_worker] Shutting down", flush=True)
        sys.exit(0)
    except Exception as exc:
        print(f"[retention_worker] Error: {exc}", flush=True)
        time.sleep(60)
