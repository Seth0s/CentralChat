"""T4 — Concurrent Stream Limiter: semáforo por tenant para POST /assistant/text/stream.

Limits the number of simultaneous SSE streams per tenant.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import (
    CENTRAL_CONCURRENT_STREAM_LIMIT_ENABLED,
    CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT,
)
from app.shared.pg_tenant import resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# tenant_id -> count of active streams
_active: dict[str, int] = {}
_lock = asyncio.Lock()


def _tenant_limit(tenant_id: str) -> int:
    """Resolve per-tenant limit, with tenant_config override if available."""
    base = max(1, int(CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT))
    try:
        from app.tenant import get_tenant_config

        cfg = get_tenant_config(tenant_id)
        if cfg is not None:
            return max(1, cfg.max_concurrent_streams)
    except Exception:
        pass
    return base


async def acquire(tenant_id: str | None = None) -> bool:
    """Try to acquire a stream slot. Returns True if allowed, False if limit reached."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    if not CENTRAL_CONCURRENT_STREAM_LIMIT_ENABLED:
        async with _lock:
            _active[tid] = _active.get(tid, 0) + 1
            try:
                from app.shared.business_metrics import STREAMS_ACTIVE

                STREAMS_ACTIVE.set(sum(_active.values()))
            except Exception:
                pass
        return True

    limit = _tenant_limit(tid)

    async with _lock:
        current = _active.get(tid, 0)
        if current >= limit:
            logger.info("concurrent_stream_limit tenant=%s current=%s limit=%s", tid, current, limit)
            return False
        _active[tid] = current + 1
        try:
            from app.shared.business_metrics import STREAMS_ACTIVE

            STREAMS_ACTIVE.set(sum(_active.values()))
        except Exception:
            pass
        return True


async def release(tenant_id: str | None = None) -> None:
    """Release a stream slot."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip()

    async with _lock:
        current = _active.get(tid, 0)
        if current > 0:
            _active[tid] = current - 1
        if _active.get(tid, 0) <= 0 and tid in _active:
            del _active[tid]
        try:
            from app.shared.business_metrics import STREAMS_ACTIVE

            STREAMS_ACTIVE.set(sum(_active.values()))
        except Exception:
            pass


def active_count(tenant_id: str | None = None) -> int:
    """Current active stream count (best-effort, non-blocking snapshot)."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    return _active.get(tid, 0)
