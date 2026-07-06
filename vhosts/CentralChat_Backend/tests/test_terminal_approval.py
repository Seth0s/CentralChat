"""Terminal tool — approval-gated shell.exec (Phase 1b)."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from app.shell_service import propose_terminal_command


class TestTerminalApproval(unittest.TestCase):
    @patch("app.shell_service.CENTRAL_PRODUCT_MODE", True)
    @patch("app.shell_service.get_request_workspace_root", return_value=None)
    def test_requires_workspace(self, *_m: object) -> None:
        out = propose_terminal_command({"command": "ls"}, "req-1")
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "workspace_not_bound")

    @patch("app.shell_service.CENTRAL_PRODUCT_MODE", True)
    @patch("app.shell_service.get_request_workspace_root")
    @patch("app.shell_service.create_pending")
    @patch("app.shell_service.resolve_tenant_id_for_store", return_value="default")
    def test_creates_shell_approval(
        self,
        _tid: object,
        mock_create: object,
        mock_root: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mock_root.return_value = tmp
            mock_create.return_value = {"approval_id": "ap-shell-1", "status": "pending"}  # type: ignore[attr-defined]
            out = propose_terminal_command(
                {"command": "echo hello", "workdir": ".", "timeout": 30},
                "req-2",
            )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("status"), "approval_required")
        self.assertEqual(out.get("action_id"), "shell.exec")
        self.assertEqual(out.get("command"), "echo hello")

    @patch("app.shell_service.CENTRAL_PRODUCT_MODE", True)
    @patch("app.shell_service.get_request_workspace_root")
    def test_blocks_elevation(self, mock_root: object) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mock_root.return_value = tmp
            out = propose_terminal_command({"command": "sudo rm -rf /"}, "req-3")
        self.assertEqual(out.get("error"), "elevation_forbidden")


if __name__ == "__main__":
    unittest.main()
