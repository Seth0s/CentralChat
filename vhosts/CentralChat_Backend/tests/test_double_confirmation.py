"""K.2 — dupla confirmacao na fila de approvals."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app.approvals_store as approvals_store
from app.action_policy import policy_flags_for_action
from app.approvals_store import (
    approve_or_first_double_step,
    confirm_double,
    create_pending,
    list_approvals,
    set_denied,
)


class TestApprovalsDoubleFlow(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        self._patch = patch.object(approvals_store, "APPROVALS_STORE_PATH", self.store_path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        os.unlink(self.store_path)

    def test_single_step_approves_directly(self) -> None:
        rec = create_pending(
            "rid",
            "process.signal",
            "P1",
            {"pid": 999},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        out = approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        assert out is not None
        self.assertEqual(out["status"], "approved")
        self.assertIn("resolved_at", out)

    def test_double_step_then_approved(self) -> None:
        rec = create_pending(
            "rid",
            "systemd.unit.restart",
            "P3",
            {"unit": "a.service"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        first = approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        assert first is not None
        self.assertEqual(first["status"], "awaiting_double_confirm")
        self.assertIn("first_confirmed_at", first)

        second = confirm_double(rec["approval_id"], tenant_id="default")
        assert second is not None
        self.assertEqual(second["status"], "approved")
        self.assertIn("second_confirmed_at", second)

    def test_deny_from_awaiting_double(self) -> None:
        rec = create_pending(
            "rid",
            "systemd.unit.restart",
            "P3",
            {"unit": "b.service"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        denied = set_denied(rec["approval_id"], tenant_id="default")
        assert denied is not None
        self.assertEqual(denied["status"], "denied")

    def test_pending_list_includes_awaiting_double(self) -> None:
        a = create_pending("r", "x", "P0", {}, tenant_id="default", requires_double_confirmation=True)
        approve_or_first_double_step(a["approval_id"], tenant_id="default")
        pending_like = list_approvals("pending", tenant_id="default")
        self.assertEqual(len(pending_like), 1)
        self.assertEqual(pending_like[0]["status"], "awaiting_double_confirm")


class TestActionPolicyReader(unittest.TestCase):
    def test_policy_flags_for_action(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "actions": {
                        "systemd.unit.restart": {
                            "requires_double_confirmation": True,
                        },
                        "systemd.unit.enable": {
                            "requires_double_confirmation": True,
                        },
                        "systemd.unit.disable": {
                            "requires_double_confirmation": True,
                        },
                    }
                },
                f,
            )
        try:
            import app.action_policy as ap

            with patch.object(ap, "SYSTEM_AGENT_POLICY_PATH", path):
                self.assertTrue(
                    policy_flags_for_action("systemd.unit.restart")["requires_double_confirmation"]
                )
                self.assertTrue(
                    policy_flags_for_action("systemd.unit.enable")["requires_double_confirmation"]
                )
                self.assertTrue(
                    policy_flags_for_action("systemd.unit.disable")["requires_double_confirmation"]
                )
                self.assertFalse(
                    policy_flags_for_action("process.signal")["requires_double_confirmation"]
                )
                self.assertTrue(
                    policy_flags_for_action("systemd.unit.restart")["requires_confirmation"]
                )
                self.assertTrue(policy_flags_for_action("process.signal")["requires_confirmation"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
