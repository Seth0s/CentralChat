"""Team rules — pending vs approved recall (Fase 3)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.memory_service as ms


class TeamRulesServiceTest(unittest.TestCase):
    def test_recall_only_approved_patterns(self) -> None:
        with patch.object(ms, "memory_db_enabled", return_value=True):
            with patch.object(ms, "ensure_team_catalog_schema"):
                mock_conn = MagicMock()
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [("Never patch prod DB",), ("Use migrations only",)]
                mock_conn.cursor.return_value.__enter__.return_value = mock_cur
                with patch.object(ms, "connect_pg") as mock_pg:
                    mock_pg.return_value.__enter__.return_value = mock_conn
                    patterns = ms.recall_approved_rule_patterns(tenant_id="acme", limit=8)
        self.assertEqual(len(patterns), 2)
        self.assertIn("Never patch prod DB", patterns[0])

    def test_propose_rule_from_rejection_empty_skips(self) -> None:
        with patch.object(ms, "memory_db_enabled", return_value=True):
            out = ms.propose_rule_from_rejection(pattern="", reason="  ")
        self.assertIsNone(out)

    def test_approve_team_rule_not_found(self) -> None:
        with patch.object(ms, "memory_db_enabled", return_value=True):
            with patch.object(ms, "ensure_team_catalog_schema"):
                mock_conn = MagicMock()
                mock_cur = MagicMock()
                mock_cur.fetchone.return_value = None
                mock_conn.cursor.return_value.__enter__.return_value = mock_cur
                with patch.object(ms, "connect_pg") as mock_pg:
                    mock_pg.return_value.__enter__.return_value = mock_conn
                    out = ms.approve_team_rule("00000000-0000-4000-8000-000000000001", tenant_id="default")
        self.assertIsNone(out)

    def test_normalize_pattern_collapses_whitespace(self) -> None:
        self.assertEqual(ms._normalize_pattern("  foo   bar  "), "foo bar")


if __name__ == "__main__":
    unittest.main()
