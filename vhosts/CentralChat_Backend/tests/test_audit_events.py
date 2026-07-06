"""H1 — audit_events append-only + export."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import app.audit_service as audit


class AuditServiceTest(unittest.TestCase):
    def test_append_skips_when_db_disabled(self) -> None:
        with patch.object(audit, "memory_db_enabled", return_value=False):
            out = audit.append_audit_event(action="auth.login")
        self.assertIsNone(out)

    def test_mirror_maps_tool_invoked(self) -> None:
        with patch.object(audit, "append_audit_event") as mock_append:
            audit.mirror_orchestrator_event(
                {"event": "tool_invoked", "tool": "read_file", "request_id": "r1"}
            )
        mock_append.assert_called_once()
        kwargs = mock_append.call_args.kwargs
        self.assertEqual(kwargs["action"], "tool.invoke")
        self.assertEqual(kwargs["resource"], "read_file")

    def test_export_csv_header(self) -> None:
        rows = [
            {
                "id": "1",
                "tenant_id": "default",
                "action": "auth.login",
                "created_at": "2026-06-14T12:00:00+00:00",
                "resource": None,
                "user_id": None,
                "session_id": None,
                "work_item_id": None,
                "metadata": {},
            }
        ]
        body = audit.export_audit_csv(rows)
        self.assertIn("action", body)
        self.assertIn("auth.login", body)

    def test_export_json_array(self) -> None:
        rows = [{"id": "1", "action": "session.turn"}]
        body = audit.export_audit_json(rows)
        parsed = json.loads(body)
        self.assertIn("items", parsed)
        self.assertEqual(parsed["items"][0]["action"], "session.turn")


if __name__ == "__main__":
    unittest.main()
