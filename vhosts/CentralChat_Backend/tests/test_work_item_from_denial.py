"""H1b — work item auto-creation on approval denial."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.work_queue as wq


class WorkItemFromDenialTest(unittest.TestCase):
    def test_title_from_path(self) -> None:
        rec = {"action_id": "file.patch", "payload": {"path": "src/auth.py"}}
        title = wq._denial_work_item_title(rec, "too risky")
        self.assertIn("file.patch", title)
        self.assertIn("auth.py", title)

    def test_skip_without_db(self) -> None:
        with patch.object(wq, "memory_db_enabled", return_value=False):
            out = wq.maybe_create_work_item_from_denial(
                approval_id="a1",
                approval_rec={"action_id": "x"},
                reason="no",
            )
        self.assertIsNone(out)

    def test_reopen_existing_item(self) -> None:
        existing = {"id": "WI-1", "status": "done", "session_id": None}
        with patch.object(wq, "memory_db_enabled", return_value=True):
            with patch.object(wq, "get_current_sub", return_value="00000000-0000-4000-8000-000000000001"):
                with patch.object(wq, "find_work_item_by_approval", return_value=existing):
                    with patch.object(wq, "patch_work_item", return_value=existing) as mock_patch:
                        with patch.object(wq, "get_work_item", return_value=existing):
                            with patch.object(wq, "append_audit_event"):
                                out = wq.maybe_create_work_item_from_denial(
                                    approval_id="ap-1",
                                    approval_rec={"session_id": "sess12345678"},
                                    reason="needs tests",
                                )
        self.assertEqual(out["id"], "WI-1")
        mock_patch.assert_called()


if __name__ == "__main__":
    unittest.main()
