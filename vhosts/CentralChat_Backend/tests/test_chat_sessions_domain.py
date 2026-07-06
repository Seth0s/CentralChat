"""L5 — regras puras de título de sessão de chat."""

from __future__ import annotations

import unittest

from app.domain.chat_sessions_domain import normalize_session_title, truncate_title


class TestChatSessionsDomain(unittest.TestCase):
    def test_normalize_empty_uses_default(self) -> None:
        self.assertEqual(normalize_session_title(None), "Nova conversa")
        self.assertEqual(normalize_session_title("   "), "Nova conversa")

    def test_normalize_truncates_long(self) -> None:
        long = "x" * 200
        out = normalize_session_title(long)
        self.assertEqual(len(out), 120)

    def test_truncate_rename_strips(self) -> None:
        self.assertEqual(truncate_title("  ab  "), "ab")

    def test_truncate_max_len(self) -> None:
        long = "y" * 200
        self.assertEqual(len(truncate_title(long)), 120)


if __name__ == "__main__":
    unittest.main()
