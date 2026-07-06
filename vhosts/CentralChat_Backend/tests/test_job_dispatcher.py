"""ADR17-4 — job dispatcher leases, retries, fairness."""
from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.client_jobs_store import (
    create_job,
    dispatch_job_to_connector,
    get_job,
    process_expired_job_leases,
)
from app.job_dispatcher import run_dispatcher_tick


def _postgres_url() -> str:
    return os.getenv(
        "TEST_MEMORY_DB_URL",
        "postgresql://central:central@127.0.0.1:5433/central_memory",
    ).strip()


def _postgres_available() -> bool:
    if os.getenv("SKIP_PG_INTEGRATION", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        import psycopg  # type: ignore

        with psycopg.connect(_postgres_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres not available on TEST_MEMORY_DB_URL")
class TestJobDispatcherIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._url = _postgres_url()
        self._suffix = str(int(time.time() * 1000) % 1_000_000)
        self._patches = [
            patch("app.config.MEMORY_DB_URL", self._url),
            patch("app.config.MEMORY_ENABLED", True),
            patch("app.pg_tenant.MEMORY_DB_URL", self._url),
            patch("app.pg_tenant.MEMORY_ENABLED", True),
            patch("app.config.CENTRAL_CLIENT_JOBS_ENABLED", True),
            patch("app.config.CENTRAL_JOB_DISPATCHER_ENABLED", True),
            patch("app.job_dispatcher.CENTRAL_JOB_DISPATCHER_ENABLED", True),
        ]
        for p in self._patches:
            p.start()
        from app.client_jobs_store import ensure_client_jobs_schema

        ensure_client_jobs_schema()
        from app.connector_registry import register_connector

        self.tenant_a = f"disp-a-{self._suffix}"
        self.tenant_b = f"disp-b-{self._suffix}"
        self.conn_a = f"conn-a-{self._suffix}"
        register_connector(
            tenant_id=self.tenant_a,
            connector_id=self.conn_a,
            capabilities=["shell.exec"],
        )
        register_connector(
            tenant_id=self.tenant_b,
            connector_id=f"conn-b-{self._suffix}",
            capabilities=["shell.exec"],
        )

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def test_dispatch_tick_moves_queued_to_dispatched(self) -> None:
        job = create_job(
            tenant_id=self.tenant_a,
            action_id="shell.exec",
            payload={"mode": "argv", "argv": ["true"]},
            tool_call_id=f"disp-tick-{self._suffix}",
        )
        self.assertEqual(job["status"], "queued")
        stats = run_dispatcher_tick()
        self.assertGreaterEqual(stats.get("dispatched", 0), 1)
        updated = get_job(tenant_id=self.tenant_a, job_id=job["job_id"])
        assert updated is not None
        self.assertEqual(updated["status"], "dispatched")
        self.assertEqual(updated["connector_id"], self.conn_a)
        self.assertIsNotNone(updated.get("lease_until"))

    def test_fairness_one_job_per_tenant_per_tick(self) -> None:
        ja = create_job(
            tenant_id=self.tenant_a,
            action_id="shell.exec",
            payload={},
            tool_call_id=f"fair-a-{self._suffix}",
        )
        jb = create_job(
            tenant_id=self.tenant_b,
            action_id="shell.exec",
            payload={},
            tool_call_id=f"fair-b-{self._suffix}",
        )
        run_dispatcher_tick()
        self.assertEqual(get_job(tenant_id=self.tenant_a, job_id=ja["job_id"])["status"], "dispatched")
        self.assertEqual(get_job(tenant_id=self.tenant_b, job_id=jb["job_id"])["status"], "dispatched")

    def test_lease_expired_requeues_then_fails(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=60)
        job = create_job(
            tenant_id=self.tenant_a,
            action_id="shell.exec",
            payload={},
            tool_call_id=f"lease-{self._suffix}",
        )
        dispatch_job_to_connector(
            tenant_id=self.tenant_a,
            job_id=job["job_id"],
            connector_id=self.conn_a,
            lease_until=past,
        )
        with patch("app.client_jobs_store.CENTRAL_CLIENT_JOB_MAX_RETRIES", 3):
            r1 = process_expired_job_leases(now=now, max_retries=3)
        self.assertEqual(r1["requeued"], 1)
        j1 = get_job(tenant_id=self.tenant_a, job_id=job["job_id"])
        assert j1 is not None
        self.assertEqual(j1["status"], "queued")
        self.assertEqual(j1["retry_count"], 1)

        from app.client_jobs_store import _connect_jobs_admin

        with _connect_jobs_admin() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE client_jobs
                    SET status = 'running', retry_count = 3, lease_until = %s, updated_at = %s
                    WHERE job_id = %s::uuid;
                    """,
                    (past, now, job["job_id"]),
                )
        with patch("app.client_jobs_store.CENTRAL_CLIENT_JOB_MAX_RETRIES", 3):
            r2 = process_expired_job_leases(now=now, max_retries=3)
        self.assertEqual(r2["failed"], 1)
        j2 = get_job(tenant_id=self.tenant_a, job_id=job["job_id"])
        assert j2 is not None
        self.assertEqual(j2["status"], "failed")
        self.assertEqual(j2["error_code"], "lease_expired")


if __name__ == "__main__":
    unittest.main()
