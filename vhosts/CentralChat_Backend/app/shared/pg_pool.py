"""T5 — Connection pool thread-safe para psycopg (Postgres).

Sobrepõe connect_pg() com um pool de conexões singleton.
Configurável via env vars (CENTRAL_PG_POOL_MIN_SIZE, CENTRAL_PG_POOL_MAX_SIZE).
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator

try:
    import psycopg  # type: ignore
except Exception:
    psycopg = None  # type: ignore

from app.config import MEMORY_DB_URL

logger = logging.getLogger(__name__)

# ── Pool config ──
_POOL_MIN = max(1, int(__import__("os").getenv("CENTRAL_PG_POOL_MIN_SIZE", "2") or "2"))
_POOL_MAX = max(_POOL_MIN + 1, int(__import__("os").getenv("CENTRAL_PG_POOL_MAX_SIZE", "8") or "8"))
_POOL_IDLE_TIMEOUT = 60.0  # seconds before idle connections are closed
_POOL_CHECK_INTERVAL = 30.0

# ── Simple thread-safe pool ──
_pool: list[_PooledConn] = []
_pool_lock = threading.Lock()
_pool_sem = threading.Semaphore(_POOL_MAX)
_pool_initialized = False
_pool_check_timer: float = 0.0


class _PooledConn:
    __slots__ = ("conn", "in_use", "last_used")

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.in_use = True
        self.last_used = time.monotonic()


def _ensure_pool() -> None:
    global _pool_initialized
    if _pool_initialized:
        return
    with _pool_lock:
        if _pool_initialized:
            return
        if psycopg is None:
            raise RuntimeError("psycopg_not_installed")
        # Pre-warm minimum connections
        for _ in range(_POOL_MIN):
            conn = psycopg.connect(MEMORY_DB_URL, autocommit=True)
            _pool.append(_PooledConn(conn))
            _pool[-1].in_use = False
        _pool_initialized = True
        logger.info("pg_pool: initialized min=%s max=%s", _POOL_MIN, _POOL_MAX)


def _reap_idle() -> None:
    """Remove idle connections above min size."""
    global _pool_check_timer
    now = time.monotonic()
    if now - _pool_check_timer < _POOL_CHECK_INTERVAL:
        return
    _pool_check_timer = now

    with _pool_lock:
        idle = [p for p in _pool if not p.in_use and now - p.last_used > _POOL_IDLE_TIMEOUT]
        if len(_pool) - len(idle) < _POOL_MIN:
            return
        for p in idle:
            try:
                p.conn.close()
            except Exception:
                pass
            _pool.remove(p)
        if idle:
            logger.debug("pg_pool: reaped %s idle connections, remaining=%s", len(idle), len(_pool))


def _get_conn() -> Any:
    """Get a connection from the pool, creating one if space allows."""
    _ensure_pool()
    _reap_idle()

    # Try to acquire semaphore with short timeout
    if not _pool_sem.acquire(timeout=5.0):
        raise RuntimeError("pg_pool_exhausted")

    try:
        with _pool_lock:
            for p in _pool:
                if not p.in_use:
                    p.in_use = True
                    p.last_used = time.monotonic()
                    return p.conn

            # No idle connection — create new one if under max
            if len(_pool) < _POOL_MAX:
                conn = psycopg.connect(MEMORY_DB_URL, autocommit=True)
                pooled = _PooledConn(conn)
                _pool.append(pooled)
                return conn

        # Should not happen due to semaphore, but fallback
        conn = psycopg.connect(MEMORY_DB_URL, autocommit=True)
        return conn
    except Exception:
        _pool_sem.release()
        raise


def _put_conn(conn: Any) -> None:
    """Return a connection to the pool."""
    with _pool_lock:
        for p in _pool:
            if p.conn is conn:
                p.in_use = False
                p.last_used = time.monotonic()
                break
    _pool_sem.release()


@contextmanager
def pool_connection() -> Generator[Any, None, None]:
    """Context manager: get a pooled connection, auto-release on exit."""
    conn = _get_conn()
    try:
        yield conn
    finally:
        _put_conn(conn)


def pool_stats() -> dict[str, Any]:
    """Debug info: current pool state."""
    with _pool_lock:
        total = len(_pool)
        in_use = sum(1 for p in _pool if p.in_use)
    return {
        "total": total,
        "in_use": in_use,
        "idle": total - in_use,
        "max": _POOL_MAX,
        "min": _POOL_MIN,
    }
