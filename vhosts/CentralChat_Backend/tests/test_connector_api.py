"""ADR17-2 — connector HTTP API + client_jobs store."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "connector-test-secret___________"


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


def _access_token(client_id: str = "tenant-a") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "connector-user",
            "client_id": client_id,
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )


def _auth_headers(client_id: str = "tenant-a") -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token(client_id)}"}


class TestConnectorApiDisabled(unittest.TestCase):
    @patch("app.http.router_connector.CENTRAL_CLIENT_JOBS_ENABLED", False)
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "off")
    def test_register_503_when_disabled(self) -> None:
        from app.server import app

        client = TestClient(app)
        r = client.post(
            "/connector/register",
            json={
                "connector_id": "c1",
                "capabilities": ["shell.exec"],
                "protocol_version": "1",
            },
        )
        self.assertEqual(r.status_code, 503)


@unittest.skipUnless(_postgres_available(), "Postgres not available on TEST_MEMORY_DB_URL")
class TestConnectorApiIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._url = _postgres_url()
        self._patches = [
            patch("app.config.MEMORY_DB_URL", self._url),
            patch("app.config.MEMORY_ENABLED", True),
            patch("app.pg_tenant.MEMORY_DB_URL", self._url),
            patch("app.pg_tenant.MEMORY_ENABLED", True),
            patch("app.config.CENTRAL_CLIENT_JOBS_ENABLED", True),
            patch("app.http.router_connector.CENTRAL_CLIENT_JOBS_ENABLED", True),
            patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required"),
            patch("app.jwt_tokens.CENTRAL_JWT_SECRET", _SECRET),
            patch("app.jwt_tokens.CENTRAL_JWT_ISSUER", ""),
            patch("app.jwt_tokens.CENTRAL_JWT_AUDIENCE", ""),
            patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id"),
        ]
        for p in self._patches:
            p.start()
        from app.client_jobs_store import ensure_client_jobs_schema

        ensure_client_jobs_schema()
        from app.server import app

        self.client = TestClient(app)
        self.connector_id = f"conn-{int(time.time() * 1000) % 100000}"

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        from app.tenant_context import set_tenant_context

        set_tenant_context(client_id=None, sub=None)

    def test_register_heartbeat_poll_result(self) -> None:
        h = _auth_headers("tenant-a")
        reg = self.client.post(
            "/connector/register",
            json={
                "connector_id": self.connector_id,
                "capabilities": ["shell.exec"],
                "protocol_version": "1",
                "device_label": "test",
            },
            headers=h,
        )
        self.assertEqual(reg.status_code, 200, reg.text)
        self.assertEqual(reg.json()["tenant_id"], "tenant-a")

        hb = self.client.post(
            "/connector/heartbeat",
            json={"connector_id": self.connector_id},
            headers=h,
        )
        self.assertEqual(hb.status_code, 200, hb.text)

        from app.client_jobs_store import create_job

        job = create_job(
            tenant_id="tenant-a",
            action_id="shell.exec",
            payload={"mode": "argv", "argv": ["true"]},
            tool_call_id=f"tc-{self.connector_id}",
        )
        self.assertEqual(job["status"], "queued")

        from app.job_dispatcher import run_dispatcher_tick

        run_dispatcher_tick()
        after_dispatch = __import__("app.client_jobs_store", fromlist=["get_job"]).get_job(
            tenant_id="tenant-a", job_id=job["job_id"]
        )
        assert after_dispatch is not None
        self.assertEqual(after_dispatch["status"], "dispatched")

        poll = self.client.get(
            "/connector/jobs",
            params={"connector_id": self.connector_id},
            headers=h,
        )
        self.assertEqual(poll.status_code, 200, poll.text)
        poll_body = poll.json()
        self.assertEqual(poll_body.get("transport"), "poll")
        items = poll_body["items"]
        self.assertTrue(any(x["job_id"] == job["job_id"] for x in items))
        self.assertEqual(items[0]["status"], "running")

        done = self.client.post(
            f"/connector/jobs/{job['job_id']}/result",
            json={
                "status": "succeeded",
                "result": {"exit_code": 0, "stdout": "ok"},
                "connector_id": self.connector_id,
            },
            headers=h,
        )
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["status"], "succeeded")

        poll2 = self.client.get(
            "/connector/jobs",
            params={"connector_id": self.connector_id},
            headers=h,
        )
        self.assertFalse(any(x["job_id"] == job["job_id"] for x in poll2.json()["items"]))

    def test_tenant_b_does_not_see_tenant_a_jobs(self) -> None:
        from app.client_jobs_store import create_job, fetch_queued_jobs

        create_job(
            tenant_id="tenant-a",
            action_id="shell.exec",
            payload={},
            tool_call_id=f"iso-a-{self.connector_id}",
        )
        jobs_b = fetch_queued_jobs(tenant_id="tenant-b", limit=50)
        self.assertFalse(any(j.get("tenant_id") == "tenant-a" for j in jobs_b))

        poll_b = self.client.get(
            "/connector/jobs",
            params={"connector_id": "other-conn"},
            headers=_auth_headers("tenant-b"),
        )
        self.assertEqual(poll_b.status_code, 200)
        self.assertFalse(
            any(j.get("tenant_id") == "tenant-a" for j in poll_b.json().get("items", []))
        )


if __name__ == "__main__":
    unittest.main()
