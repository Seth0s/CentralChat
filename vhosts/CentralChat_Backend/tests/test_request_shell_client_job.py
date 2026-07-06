"""ADR17-3 — request_shell tenant path: HITL → approve → client_job (no VPS gateway)."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from app.client_shell_execution import PENDING_HITL_MESSAGE_PT
from app.request_shell_tool import dispatch_request_shell

_SECRET = "shell-phase3-test-secret________"


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


def _access_token(client_id: str = "tenant-shell") -> str:
    now = int(time.time())
    return jwt.encode(
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


class TestRequestShellClientPathUnit(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.request_shell_tool.call_shell_gateway_run")
    @patch("app.request_shell_tool.connector_online_for_tenant", return_value=True)
    @patch("app.request_shell_tool.enqueue_shell_exec_client_job")
    def test_p0_enqueues_job_not_gateway(
        self,
        mock_enqueue: unittest.mock.MagicMock,
        _online: unittest.mock.MagicMock,
        mock_gw: unittest.mock.MagicMock,
    ) -> None:
        mock_enqueue.return_value = {"job_id": "j1", "status": "queued"}
        out = dispatch_request_shell(
            arguments={
                "mode": "argv",
                "argv": ["ls", "/central"],
                "cwd": "/central",
                "intent": "listar",
            },
            request_id="req-p0",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("status"), "job_queued")
        mock_gw.assert_not_called()
        mock_enqueue.assert_called_once()

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.request_shell_tool.call_shell_gateway_run")
    @patch("app.request_shell_tool.connector_online_for_tenant", return_value=False)
    def test_p0_offline_error(
        self,
        _online: unittest.mock.MagicMock,
        mock_gw: unittest.mock.MagicMock,
    ) -> None:
        out = dispatch_request_shell(
            arguments={
                "mode": "argv",
                "argv": ["ls", "/central"],
                "cwd": "/central",
                "intent": "listar",
            },
            request_id="req-off",
        )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "client_agent_offline")
        mock_gw.assert_not_called()

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.request_shell_tool.call_shell_gateway_run")
    @patch("app.request_shell_tool.create_pending")
    def test_p3_pending_hitl_no_gateway(
        self,
        mock_pending: unittest.mock.MagicMock,
        mock_gw: unittest.mock.MagicMock,
    ) -> None:
        mock_pending.return_value = {
            "approval_id": "a1",
            "status": "pending",
            "tenant_id": "default",
        }
        out = dispatch_request_shell(
            arguments={
                "mode": "sh_c",
                "sh_c": "ls -la",
                "intent": "listar",
            },
            request_id="req-p3",
        )
        self.assertEqual(out.get("status"), "pending_hitl")
        self.assertEqual(out.get("message_pt"), PENDING_HITL_MESSAGE_PT)
        mock_gw.assert_not_called()
        mock_pending.assert_called_once()

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
    @patch("app.request_shell_tool.call_shell_gateway_run")
    @patch("app.request_shell_tool.connector_online_for_tenant", return_value=False)
    def test_legacy_p0_uses_gateway(
        self,
        _online: unittest.mock.MagicMock,
        mock_gw: unittest.mock.MagicMock,
    ) -> None:
        mock_gw.return_value = {
            "ok": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "truncated": False,
            "timed_out": False,
        }
        out = dispatch_request_shell(
            arguments={
                "mode": "argv",
                "argv": ["ls", "/central"],
                "cwd": "/central",
                "intent": "listar",
            },
            request_id="req-leg",
        )
        self.assertEqual(out.get("status"), "executed")
        mock_gw.assert_called_once()


@unittest.skipUnless(_postgres_available(), "Postgres not available on TEST_MEMORY_DB_URL")
class TestRequestShellApproveEnqueueIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._url = _postgres_url()
        self._connector_id = f"shell-conn-{int(time.time() * 1000) % 100000}"
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
        self.headers = {"Authorization": f"Bearer {_access_token('tenant-shell')}"}
        reg = self.client.post(
            "/connector/register",
            json={
                "connector_id": self._connector_id,
                "capabilities": ["shell.exec"],
                "protocol_version": "1",
            },
            headers=self.headers,
        )
        self.assertEqual(reg.status_code, 200, reg.text)

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        from app.tenant_context import set_tenant_context

        set_tenant_context(client_id=None, sub=None)

    def test_p3_approve_creates_queued_job(self) -> None:
        from app.tenant_context import set_tenant_context

        set_tenant_context(client_id="tenant-shell", sub="u1")
        out = dispatch_request_shell(
            arguments={"mode": "sh_c", "sh_c": "echo hi", "intent": "teste hitl"},
            request_id="req-hitl-flow",
        )
        self.assertEqual(out.get("status"), "pending_hitl")
        approval_id = out["approval"]["approval_id"]

        approve = self.client.post(
            f"/approvals/{approval_id}/approve",
            headers=self.headers,
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        body = approve.json()
        self.assertEqual(body.get("status"), "approved")
        self.assertIn("client_job_id", body)
        job_id = body["client_job_id"]

        from app.job_dispatcher import run_dispatcher_tick

        run_dispatcher_tick()

        poll = self.client.get(
            "/connector/jobs",
            params={"connector_id": self._connector_id},
            headers=self.headers,
        )
        self.assertEqual(poll.status_code, 200)
        jobs = poll.json()["items"]
        match = [j for j in jobs if j["job_id"] == job_id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["action_id"], "shell.exec")
        self.assertEqual(match[0]["status"], "running")
        self.assertEqual(match[0]["approval_id"], approval_id)
        payload = match[0]["payload"]
        self.assertEqual(payload.get("mode"), "sh_c")
        self.assertEqual(payload.get("sh_c"), "echo hi")


if __name__ == "__main__":
    unittest.main()
