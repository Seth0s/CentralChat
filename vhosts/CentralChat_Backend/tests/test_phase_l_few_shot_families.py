"""L1-3 — few-shots por familia no historico do tool_loop."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_tools_phase_l import build_few_shot_messages


class TestPhaseLFewShotFamilies(unittest.TestCase):
    def test_disabled_returns_empty(self) -> None:
        self.assertEqual(build_few_shot_messages(enabled=False), [])

    def test_base_only_when_families_off(self) -> None:
        with patch("app.agent_tools_phase_l.AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED", False):
            few = build_few_shot_messages(enabled=True)
        self.assertEqual(len(few), 4)
        self.assertEqual(few[0]["role"], "user")

    def test_includes_families_when_on(self) -> None:
        with patch("app.agent_tools_phase_l.AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED", True):
            few = build_few_shot_messages(enabled=True)
        self.assertEqual(len(few), 10)
        joined = " ".join(m.get("content", "") for m in few)
        self.assertIn("request_shell", joined)
        self.assertNotIn("create_approval_request", joined)
        self.assertIn("run_shell_command", joined)


if __name__ == "__main__":
    unittest.main()
