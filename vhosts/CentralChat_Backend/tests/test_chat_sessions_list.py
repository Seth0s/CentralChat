"""Listagem de sessões — só conversas com mensagens (§11)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.chat_sessions as cs


class ChatSessionsListMetaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "chat_sessions.json"
        self._path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "sessions": [
                        {
                            "id": "11111111-1111-4111-8111-111111111111",
                            "title": "Nova conversa",
                            "pinned": False,
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "updated_at": "2026-01-01T00:00:00+00:00",
                            "messages": [],
                        },
                        {
                            "id": "22222222-2222-4222-8222-222222222222",
                            "title": "Com histórico",
                            "pinned": False,
                            "created_at": "2026-01-02T00:00:00+00:00",
                            "updated_at": "2026-01-02T00:00:00+00:00",
                            "messages": [
                                {"role": "user", "content": "olá"},
                                {"role": "assistant", "content": "oi"},
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch.object(cs, "CHAT_SESSIONS_EVENT_LOG_ENABLED", False)
    @patch.object(cs, "_store_path")
    def test_list_excludes_empty_and_prunes_store(self, mock_path: object) -> None:
        mock_path.return_value = self._path
        items = cs.list_sessions_meta()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "22222222-2222-4222-8222-222222222222")
        self.assertEqual(items[0]["message_count"], 2)
        data = json.loads(self._path.read_text(encoding="utf-8"))
        ids = [s["id"] for s in data["sessions"]]
        self.assertEqual(ids, ["22222222-2222-4222-8222-222222222222"])


if __name__ == "__main__":
    unittest.main()
