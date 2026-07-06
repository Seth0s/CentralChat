"""Onda B — B1.5 approve/deny idempotent (double-click safe)."""

from __future__ import annotations

import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "approval-idem-secret______________"


def _token(*, sub: str = "approver-1", client_id: str = "tenant-a") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "client_id": client_id,
            "role": "approver",
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )


class TestApprovalIdempotencyHttp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.audit_events: list[dict] = []
        self._patches = [
            patch("app.config.CENTRAL_ROOT", self.tmp.name),
            patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required"),
            patch("app.auth.CENTRAL_JWT_SECRET", _SECRET),
            patch("app.auth.CENTRAL_JWT_ISSUER", ""),
            patch("app.auth.CENTRAL_JWT_AUDIENCE", ""),
            patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id"),
            patch(
                "app.approvals.write_orchestrator_audit",
                side_effect=lambda ev: self.audit_events.append(dict(ev)),
            ),
            patch("app.approvals._dispatch_approved_job", return_value={"job_id": "job-1"}),
            patch("app.approvals.maybe_enqueue_shell_job_after_approval", return_value=None),
        ]
        for p in self._patches:
            p.start()
        from app.server import app

        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {_token()}"}

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()

    def _create_test_approval(self) -> str:
        r = self.client.post(
            "/approvals/test",
            headers=self.headers,
            json={"action_id": "test.echo", "payload": {"hello": "world"}},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["approval_id"]

    def test_double_approve_is_idempotent(self) -> None:
        approval_id = self._create_test_approval()
        first = self.client.post(f"/approvals/{approval_id}/approve", headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json().get("status"), "approved")
        self.assertNotIn("idempotent_replay", first.json())

        second = self.client.post(f"/approvals/{approval_id}/approve", headers=self.headers)
        self.assertEqual(second.status_code, 200, second.text)
        body = second.json()
        self.assertEqual(body.get("status"), "approved")
        self.assertTrue(body.get("idempotent_replay"))
        self.assertEqual(len([e for e in self.audit_events if e.get("event") == "approval_resolved"]), 1)

    def test_double_deny_is_idempotent(self) -> None:
        approval_id = self._create_test_approval()
        first = self.client.post(
            f"/approvals/{approval_id}/deny",
            headers=self.headers,
            json={"reason": "policy"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json().get("status"), "denied")

        second = self.client.post(
            f"/approvals/{approval_id}/deny",
            headers=self.headers,
            json={"reason": "policy"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json().get("idempotent_replay"))
        self.assertEqual(len([e for e in self.audit_events if e.get("resolution") == "denied"]), 1)

    def test_approve_after_deny_returns_409(self) -> None:
        approval_id = self._create_test_approval()
        deny = self.client.post(f"/approvals/{approval_id}/deny", headers=self.headers)
        self.assertEqual(deny.status_code, 200, deny.text)

        approve = self.client.post(f"/approvals/{approval_id}/approve", headers=self.headers)
        self.assertEqual(approve.status_code, 409, approve.text)

    def test_deny_after_approve_returns_409(self) -> None:
        approval_id = self._create_test_approval()
        approve = self.client.post(f"/approvals/{approval_id}/approve", headers=self.headers)
        self.assertEqual(approve.status_code, 200, approve.text)

        deny = self.client.post(f"/approvals/{approval_id}/deny", headers=self.headers)
        self.assertEqual(deny.status_code, 409, deny.text)


class TestApprovalIdempotencyStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch("app.config.CENTRAL_ROOT", self.tmp.name)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_awaiting_double_confirm_replay_on_second_approve(self) -> None:
        from app.shared.approvals_store import (
            approve_or_first_double_step,
            create_pending,
        )

        rec = create_pending(
            "r1",
            "systemd.unit.restart",
            "P3",
            {"unit": "a.service"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        first = approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        assert first is not None
        self.assertTrue(first.changed)
        self.assertEqual(first["status"], "awaiting_double_confirm")

        second = approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        assert second is not None
        self.assertFalse(second.changed)
        self.assertEqual(second["status"], "awaiting_double_confirm")


if __name__ == "__main__":
    unittest.main()
