"""B3.3 — thinking redacted must not leak in audit export."""

from __future__ import annotations

import unittest

from app.shared.redacted_thinking import assistant_message_for_history, split_redacted_thinking_body


class TestThinkingExportSafety(unittest.TestCase):
    def test_strip_removes_thinking_tags(self) -> None:
        raw = "Hello <thinking>secret plan</thinking> world"
        remainder, inner = split_redacted_thinking_body(raw)
        self.assertEqual(inner, "secret plan")
        self.assertNotIn("secret plan", remainder)
        self.assertIn("world", remainder)

    def test_history_sanitizer(self) -> None:
        raw = "<thinking>internal</thinking>public reply"
        out = assistant_message_for_history(raw)
        self.assertNotIn("internal", out)
        self.assertIn("public reply", out)
