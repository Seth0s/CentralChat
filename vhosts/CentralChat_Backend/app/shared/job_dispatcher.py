"""ADR-017 phase 4 — background dispatcher: queued → dispatched, lease expiry, fairness."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from app.connector import (
    client_jobs_db_enabled,
    dispatch_job_to_connector,
    pick_fair_queued_jobs,
    process_expired_job_leases,
)
from app.config import (
    CENTRAL_CLIENT_JOB_LEASE_SECONDS,
    CENTRAL_JOB_DISPATCHER_BATCH_SIZE,
    CENTRAL_JOB_DISPATCHER_ENABLED,
    CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS,
)
from app.connector import list_online_connectors

logger = logging.getLogger(__name__)

_dispatcher_task: asyncio.Task[None] | None = None
_rr_tenant_offset: int = 0


def _connector_supports_action(connector: dict[str, Any], action_id: str) -> bool:
    caps = connector.get("capabilities") or []
    if not caps:
        return True
    return action_id in caps or "*" in caps


def _pick_connector_for_job(*, tenant_id: str, action_id: str) -> dict[str, Any] | None:
    online = list_online_connectors(tenant_id=tenant_id)
    for c in online:
        if _connector_supports_action(c, action_id):
            return c
    return online[0] if online else None


def run_dispatcher_tick(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Single dispatcher iteration: reclaim leases, dispatch queued jobs to online connectors.

    Fairness: at most one queued job per tenant per tick (``pick_fair_queued_jobs``).
    Poll-only MVP: connectors pull work via ``GET /connector/jobs`` (no WebSocket push).
    """
    if not CENTRAL_JOB_DISPATCHER_ENABLED or not client_jobs_db_enabled():
        return {"enabled": False, "dispatched": 0, "requeued": 0, "failed": 0, "skipped_no_connector": 0}

    ts = now or datetime.now(timezone.utc)
    lease_until_default = ts + timedelta(seconds=CENTRAL_CLIENT_JOB_LEASE_SECONDS)
    expired = process_expired_job_leases(now=ts)
    candidates = pick_fair_queued_jobs(limit=CENTRAL_JOB_DISPATCHER_BATCH_SIZE)

    global _rr_tenant_offset  # noqa: PLW0603
    if candidates:
        candidates = sorted(candidates, key=lambda j: (j["tenant_id"], j.get("created_at") or ""))
        rotated = candidates[_rr_tenant_offset:] + candidates[:_rr_tenant_offset]
        _rr_tenant_offset = (_rr_tenant_offset + 1) % max(1, len(candidates))

    dispatched = 0
    skipped_no_connector = 0
    for job in (rotated if candidates else []):
        tid = str(job["tenant_id"])
        action_id = str(job.get("action_id") or "")
        connector = _pick_connector_for_job(tenant_id=tid, action_id=action_id)
        if not connector:
            skipped_no_connector += 1
            continue
        out = dispatch_job_to_connector(
            tenant_id=tid,
            job_id=str(job["job_id"]),
            connector_id=str(connector["connector_id"]),
            lease_until=lease_until_default,
        )
        if out:
            dispatched += 1

    return {
        "enabled": True,
        "dispatched": dispatched,
        "requeued": expired["requeued"],
        "failed": expired["failed"],
        "skipped_no_connector": skipped_no_connector,
        "candidates": len(candidates),
    }


async def _dispatcher_loop() -> None:
    interval = CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS
    while True:
        try:
            stats = await asyncio.to_thread(run_dispatcher_tick)
            if stats.get("dispatched") or stats.get("requeued") or stats.get("failed"):
                logger.debug("job_dispatcher_tick %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("job_dispatcher_tick_failed")
        await asyncio.sleep(interval)


def start_job_dispatcher() -> None:
    """Start background asyncio task (idempotent)."""
    global _dispatcher_task  # noqa: PLW0603
    if not CENTRAL_JOB_DISPATCHER_ENABLED or not client_jobs_db_enabled():
        return
    if _dispatcher_task is not None and not _dispatcher_task.done():
        return
    _dispatcher_task = asyncio.create_task(_dispatcher_loop(), name="central_job_dispatcher")
    logger.info("job_dispatcher_started interval=%ss", CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS)


def stop_job_dispatcher() -> None:
    global _dispatcher_task  # noqa: PLW0603
    if _dispatcher_task is None:
        return
    _dispatcher_task.cancel()
    with suppress(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(_dispatcher_task)
    _dispatcher_task = None
    logger.info("job_dispatcher_stopped")


async def stop_job_dispatcher_async() -> None:
    """Async shutdown for FastAPI lifespan."""
    global _dispatcher_task  # noqa: PLW0603
    if _dispatcher_task is None:
        return
    _dispatcher_task.cancel()
    with suppress(asyncio.CancelledError):
        await _dispatcher_task
    _dispatcher_task = None


def main() -> None:
    """Run dispatcher loop in foreground (``python -m app.job_dispatcher``)."""
    import time

    logging.basicConfig(level=logging.INFO)
    logger.info("job_dispatcher_foreground interval=%ss", CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS)
    try:
        while True:
            stats = run_dispatcher_tick()
            logger.info("tick %s", stats)
            time.sleep(CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("job_dispatcher_stopped")


if __name__ == "__main__":
    main()
