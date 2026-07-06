"""Fase 0 P2 — action_policy: fila, requires_confirmation, placeholders P2."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app.action_policy as ap
from app.action_policy import (
    APPROVAL_QUEUE_ACTION_IDS,
    P2_RESERVED_ACTION_IDS,
    policy_flags_for_action,
    risk_level_for_action,
)
from app.approval_via_tool import ALLOWED_APPROVAL_ACTION_IDS


class TestApprovalQueueIdsParity(unittest.TestCase):
    def test_queue_ids_match_tool_allowlist(self) -> None:
        self.assertEqual(APPROVAL_QUEUE_ACTION_IDS, ALLOWED_APPROVAL_ACTION_IDS)


class TestPolicyFlagsRequiresConfirmation(unittest.TestCase):
    def test_desktop_open_url_true_without_system_agent_entry(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"actions": {}}, f)
        try:
            with patch.object(ap, "SYSTEM_AGENT_POLICY_PATH", path):
                flags = policy_flags_for_action("desktop.open_url")
                self.assertTrue(flags["requires_confirmation"])
                self.assertFalse(flags["requires_double_confirmation"])
        finally:
            os.unlink(path)

    def test_explicit_requires_confirmation_false(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "actions": {
                        "custom.test": {
                            "requires_confirmation": False,
                            "requires_double_confirmation": False,
                        }
                    }
                },
                f,
            )
        try:
            with patch.object(ap, "SYSTEM_AGENT_POLICY_PATH", path):
                flags = policy_flags_for_action("custom.test")
                self.assertFalse(flags["requires_confirmation"])
        finally:
            os.unlink(path)


class TestP2ReservedRiskLevel(unittest.TestCase):
    def test_reserved_ids_p2_when_not_in_policy_file(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"actions": {}}, f)
        try:
            with patch.object(ap, "SYSTEM_AGENT_POLICY_PATH", path):
                for aid in P2_RESERVED_ACTION_IDS:
                    self.assertEqual(risk_level_for_action(aid), "P2")
        finally:
            os.unlink(path)

    def test_policy_entry_overrides_reserved_fallback(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "actions": {
                        "systemd.unit.stop": {
                            "allowed": False,
                            "risk_level": "P3",
                            "requires_confirmation": True,
                            "reason": "test_override",
                        }
                    }
                },
                f,
            )
        try:
            with patch.object(ap, "SYSTEM_AGENT_POLICY_PATH", path):
                self.assertEqual(risk_level_for_action("systemd.unit.stop"), "P3")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
