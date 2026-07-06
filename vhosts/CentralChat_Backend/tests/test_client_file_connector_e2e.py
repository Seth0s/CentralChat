"""ADR17-7 — file.read job lifecycle with mock connector result (Postgres)."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "client-file-e2e-secret________"


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


def _auth_headers(client_id: str = "tenant-file") -> dict[str, str]:
    now = int(time.time())
    tok = jwt.encode(
        {
            "sub": "u1",
            "client_id": client_id,
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {tok}"}


@unittest.skipUnless(_postgres_available(), "Postgres not available")
class TestClientFileJobE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._url = _postgres_url()
        self._patches = [
            patch("app.config.MEMORY_DB_URL", self._url),
            patch("app.config.MEMORY_ENABLED", True),
            patch("app.pg_tenant.MEMORY_DB_URL", self._url),
            patch("app.pg_tenant.MEMORY_ENABLED", True),
            patch("app.config.CENTRAL_CLIENT_JOBS_ENABLED", True),
            patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False),
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
        self.connector_id = f"file-conn-{int(time.time() * 1000) % 100000}"
        self.tenant = "tenant-file"
        h = _auth_headers(self.tenant)
        self.client.post(
            "/connector/register",
            json={
                "connector_id": self.connector_id,
                "capabilities": ["file.read", "file.grep", "shell.exec"],
                "protocol_version": "1",
            },
            headers=h,
        )
        self.client.post(
            "/connector/heartbeat",
            json={"connector_id": self.connector_id},
            headers=h,
        )

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    @patch("app.client_file_tools.connector_online_for_tenant", return_value=True)
    def test_dispatch_read_then_connector_result(self, _online: unittest.mock.MagicMock) -> None:
        from app.client_file_tools import dispatch_client_read_file
        from app.job_dispatcher import run_dispatcher_tick
        from app.tenant_context import set_tenant_context

        hosts = "/etc/hosts"
        if not os.path.isfile(hosts):
            self.skipTest("no /etc/hosts")

        set_tenant_context(client_id=self.tenant, sub="u1")
        out = dispatch_client_read_file(
            arguments={"path": hosts, "max_bytes": 1024},
            request_id="req-file-e2e",
        )
        self.assertEqual(out.get("status"), "job_queued")
        job_id = out.get("job_id")
        assert job_id

        run_dispatcher_tick()
        h = _auth_headers(self.tenant)
        poll = self.client.get(
            "/connector/jobs",
            params={"connector_id": self.connector_id},
            headers=h,
        )
        items = poll.json()["items"]
        self.assertTrue(any(x["job_id"] == job_id for x in items))

        root = Path(__file__).resolve().parents[2] / "connector"
        sys.path.insert(0, str(root))
        from central_connector.handlers import execute_file_read

        result = execute_file_read({"path": hosts, "max_bytes": 1024})
        self.assertTrue(result.get("ok"))

        done = self.client.post(
            f"/connector/jobs/{job_id}/result",
            json={
                "status": "succeeded",
                "result": result,
                "connector_id": self.connector_id,
            },
            headers=h,
        )
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
