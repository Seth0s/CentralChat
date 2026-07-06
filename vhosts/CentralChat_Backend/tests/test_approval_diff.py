"""Approval diff endpoint (Phase 1)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestApprovalDiff(unittest.TestCase):
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "off")
    @patch("app.approvals.resolve_tenant_id_for_store", return_value="default")
    @patch("app.approvals.get_approval")
    def test_diff_returns_unified_diff(self, mock_get: object, *_m: object) -> None:
        mock_get.return_value = {
            "approval_id": "aid-1",
            "action_id": "file.patch",
            "status": "pending",
            "payload": {
                "path": "/tmp/foo.py",
                "diff": "--- a/foo\n+++ b/foo\n@@\n-old\n+new\n",
                "summary": "+1 -1 lines",
            },
        }
        from app.server import app

        r = TestClient(app).get("/approvals/aid-1/diff")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("diff", body)
        self.assertIn("+new", body["diff"])

    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "off")
    @patch("app.approvals.resolve_tenant_id_for_store", return_value="default")
    @patch("app.approvals.get_approval")
    def test_diff_shell_preview(self, mock_get: object, *_m: object) -> None:
        mock_get.return_value = {
            "approval_id": "aid-2",
            "action_id": "shell.exec",
            "status": "pending",
            "payload": {
                "mode": "sh_c",
                "sh_c": "npm test",
                "cwd": "/tmp/proj",
                "preview": "npm test",
                "intent": "npm test",
            },
        }
        from app.server import app

        r = TestClient(app).get("/approvals/aid-2/diff")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body.get("kind"), "shell")
        self.assertEqual(body.get("command"), "npm test")


if __name__ == "__main__":
    unittest.main()
