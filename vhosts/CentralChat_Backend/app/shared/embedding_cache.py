"""T7 — Embedding cache (LRU) + async job queue (Postgres LISTEN/NOTIFY).

Cache: thread-safe LRU to avoid re-embedding identical text.
Queue: enqueue jobs via Postgres table; worker polls or LISTENs.
Worker: standalone script (scripts/embedding_worker.py) or inline.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from app.config import MEMORY_DB_URL, MEMORY_ENABLED
from app.shared.pg_tenant import memory_db_enabled

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# LRU CACHE
# ═══════════════════════════════════════════════════════════════════

_CACHE_MAX_SIZE = int(__import__("os").getenv("EMBEDDING_CACHE_SIZE", "512") or "512")
_cache: OrderedDict[str, tuple[list[float], str]] = OrderedDict()
_cache_lock = threading.Lock()
_cache_hits = 0
_cache_misses = 0


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_cache_get(text: str) -> tuple[list[float], str] | None:
    """Returns (embedding_vector, model_id) or None if cache miss."""
    global _cache_hits, _cache_misses
    key = _cache_key(text)
    with _cache_lock:
        result = _cache.get(key)
        if result is not None:
            _cache.move_to_end(key)
            _cache_hits += 1
            return result[0][:], result[1]  # return copies
        _cache_misses += 1
    return None


def embedding_cache_set(text: str, embedding: list[float], model_id: str) -> None:
    """Store embedding result in LRU cache."""
    key = _cache_key(text)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
        else:
            _cache[key] = (list(embedding), model_id)
            while len(_cache) > _CACHE_MAX_SIZE:
                _cache.popitem(last=False)


def embedding_cache_stats() -> dict[str, Any]:
    """Cache hit/miss/size statistics."""
    with _cache_lock:
        return {
            "size": len(_cache),
            "max_size": _CACHE_MAX_SIZE,
            "hits": _cache_hits,
            "misses": _cache_misses,
            "hit_ratio": round(_cache_hits / max(1, _cache_hits + _cache_misses), 3),
        }


def embedding_cache_clear() -> None:
    """Clear the entire cache."""
    global _cache_hits, _cache_misses
    with _cache_lock:
        _cache.clear()
        _cache_hits = 0
        _cache_misses = 0


# ═══════════════════════════════════════════════════════════════════
# ASYNC JOB QUEUE (Postgres)
# ═══════════════════════════════════════════════════════════════════


def _ensure_jobs_table(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_jobs (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     TEXT NOT NULL DEFAULT 'default',
            kind          TEXT NOT NULL DEFAULT 'query',
            source_key    TEXT,
            input_text    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',
            embedding     vector(384),
            embedding_model_id TEXT,
            error_message TEXT,
            priority      INT NOT NULL DEFAULT 0,
            attempts      INT NOT NULL DEFAULT 0,
            max_attempts  INT NOT NULL DEFAULT 3,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at    TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ
        );
        """
    )


def enqueue_embedding_job(
    *,
    text: str,
    tenant_id: str = "default",
    kind: str = "query",
    source_key: str | None = None,
    priority: int = 0,
) -> int | None:
    """Insert a pending embedding job. Returns job ID or None if DB unavailable."""
    if not memory_db_enabled():
        return None

    try:
        import psycopg
    except Exception:
        return None

    try:
        conn = psycopg.connect(MEMORY_DB_URL, autocommit=True)
        cur = conn.cursor()
        _ensure_jobs_table(cur)
        cur.execute(
            """INSERT INTO embedding_jobs (tenant_id, kind, source_key, input_text, priority)
               VALUES (%s, %s, %s, %s, %s) RETURNING id;""",
            (tenant_id, kind, source_key, text[:8000], priority),
        )
        job_id = int(cur.fetchone()[0])
        conn.close()
        return job_id
    except Exception as exc:
        logger.warning("embedding_enqueue_failed: %s", exc)
        return None


def embedding_queue_stats() -> dict[str, Any]:
    """Pending/completed/failed counts from embedding_jobs table."""
    if not memory_db_enabled():
        return {"pending": 0, "processing": 0, "done": 0, "failed": 0, "available": False}

    try:
        import psycopg
    except Exception:
        return {"available": False}

    try:
        conn = psycopg.connect(MEMORY_DB_URL, autocommit=True)
        cur = conn.cursor()
        _ensure_jobs_table(cur)
        counts = {}
        for status in ("pending", "processing", "done", "failed"):
            cur.execute("SELECT COUNT(*) FROM embedding_jobs WHERE status = %s;", (status,))
            counts[status] = int(cur.fetchone()[0] or 0)
        conn.close()
        counts["available"] = True
        return counts
    except Exception:
        return {"available": False}
