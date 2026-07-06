#!/usr/bin/env python3
"""T7 — Embedding Worker (standalone process).

Polls embedding_jobs table for pending work. When a job is found:
1. Claims it (status → 'processing')
2. Computes the embedding
3. Stores the result (status → 'done')
4. LISTENs for NOTIFY to wake up immediately on new jobs.

Usage:
    python scripts/embedding_worker.py [--once] [--db-url URL]
    --once: process one batch and exit
"""

import hashlib
import math
import os
import select
import sys
import time
from typing import Any

# Resolve DB URL
DB_URL = os.getenv("MEMORY_DB_URL", "")
for arg in sys.argv:
    if arg.startswith("--db-url="):
        DB_URL = arg.split("=", 1)[1]

if not DB_URL:
    print("ERROR: Set MEMORY_DB_URL or pass --db-url", file=sys.stderr)
    sys.exit(1)

ONCE = "--once" in sys.argv

# ── Connect ──
import psycopg

conn = psycopg.connect(DB_URL, autocommit=True)
cur = conn.cursor()

# ── Ensure schema ──
cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
cur.execute(
    """CREATE TABLE IF NOT EXISTS embedding_jobs (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'default',
        kind TEXT DEFAULT 'query', source_key TEXT, input_text TEXT NOT NULL,
        status TEXT DEFAULT 'pending', embedding vector(384),
        embedding_model_id TEXT, error_message TEXT, priority INT DEFAULT 0,
        attempts INT DEFAULT 0, max_attempts INT DEFAULT 3,
        created_at TIMESTAMPTZ DEFAULT now(),
        started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ);"""
)

# ── Simple hash-based embedding (CPU, no GPU needed) ──
EMBEDDING_DIM = 384


def compute_embedding(text: str) -> list[float]:
    """Deterministic hash-based embedding (same as embed_local_hash but 384d)."""
    vec = [0.0] * EMBEDDING_DIM
    for tok in (text or "").lower().split():
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16], 16)
        idx = h % EMBEDDING_DIM
        sign = -1.0 if (h >> 63) & 1 else 1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def process_one_job() -> bool:
    """Claim and process one pending job. Returns True if a job was processed."""
    cur.execute(
        """UPDATE embedding_jobs
           SET status = 'processing', started_at = now(), attempts = attempts + 1
           WHERE id = (
               SELECT id FROM embedding_jobs
               WHERE status = 'pending' AND attempts < max_attempts
               ORDER BY priority DESC, created_at ASC
               LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING id, input_text;"""
    )
    row = cur.fetchone()
    if not row:
        return False

    job_id, text = int(row[0]), str(row[1])

    try:
        vec = compute_embedding(text)
        cur.execute(
            f"""UPDATE embedding_jobs
                SET status = 'done', embedding = '{_vec_literal(vec)}'::vector,
                    embedding_model_id = 'local_hash_v1', completed_at = now()
                WHERE id = %s;""",
            (job_id,),
        )
        print(f"[embedding_worker] job {job_id}: done ({len(text)} chars)", flush=True)
    except Exception as exc:
        cur.execute(
            "UPDATE embedding_jobs SET status = 'failed', error_message = %s WHERE id = %s;",
            (str(exc)[:500], job_id),
        )
        print(f"[embedding_worker] job {job_id}: failed ({exc})", flush=True)

    return True


def process_batch(max_jobs: int = 10) -> int:
    """Process up to max_jobs pending jobs."""
    processed = 0
    for _ in range(max_jobs):
        if not process_one_job():
            break
        processed += 1
    return processed


# ── LISTEN loop ──
cur.execute("LISTEN embedding_jobs;")

print(f"[embedding_worker] started, listening on embedding_jobs channel", flush=True)

if ONCE:
    n = process_batch(max_jobs=100)
    print(f"[embedding_worker] --once: processed {n} jobs, exiting", flush=True)
    conn.close()
    sys.exit(0)

while True:
    n = process_batch(max_jobs=10)

    # Wait for NOTIFY or timeout
    if n > 0:
        timeout = 0.1  # more jobs likely
    else:
        timeout = 5.0  # idle

    try:
        if select.select([conn], [], [], timeout)[0]:
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
    except (KeyboardInterrupt, SystemExit):
        print("[embedding_worker] shutting down", flush=True)
        conn.close()
        sys.exit(0)
    except Exception as exc:
        print(f"[embedding_worker] error: {exc}", flush=True)
        time.sleep(1)
