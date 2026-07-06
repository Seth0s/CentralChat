"""Phase 2 — session event log, migration, projection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.context.projection import LinearTranscriptProjection
from app.context.session_event_migration import migrate_legacy_chat_sessions
from app.context.types import SessionEvent, SessionEventType
from app.repositories.session_event_store import SessionEventStore
from app import chat_sessions as cs


class TestLinearTranscriptProjection(unittest.TestCase):
    def test_projects_user_assistant_and_tool_summaries(self) -> None:
        from datetime import datetime, timezone

        base = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        events = [
            SessionEvent(
                tenant_id="t1",
                session_id="sess-12345678",
                event_type=SessionEventType.USER_MESSAGE,
                payload={"content": "hi"},
                ts=base,
            ),
            SessionEvent(
                tenant_id="t1",
                session_id="sess-12345678",
                event_type=SessionEventType.TOOL_CALL,
                payload={"tool": "grep_workspace"},
                ts=base,
            ),
            SessionEvent(
                tenant_id="t1",
                session_id="sess-12345678",
                event_type=SessionEventType.ASSISTANT_MESSAGE,
                payload={"content": "hello"},
                ts=base,
            ),
        ]
        out = LinearTranscriptProjection().project(events)
        self.assertEqual(
            out,
            [
                {"role": "user", "content": "hi"},
                {"role": "system", "content": "[tool_call] grep_workspace"},
                {"role": "assistant", "content": "hello"},
            ],
        )


class TestSessionEventMigration(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.events_path = Path(self._td.name) / "session_events.jsonl"
        self.store = SessionEventStore()

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("app.repositories.session_event_store._events_path")
    @patch("app.repositories.session_event_store._meta_path")
    def test_migrate_legacy_idempotent(self, mock_meta: unittest.mock.MagicMock, mock_ev: unittest.mock.MagicMock) -> None:
        mock_ev.return_value = self.events_path
        mock_meta.return_value = self.events_path.with_suffix(".meta.json")
        legacy = {
            "schema": 1,
            "sessions": [
                {
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "title": "T",
                    "updated_at": "2026-05-16T12:00:00+00:00",
                    "messages": [
                        {"role": "user", "content": "u1"},
                        {"role": "assistant", "content": "a1"},
                    ],
                }
            ],
        }
        n1 = migrate_legacy_chat_sessions(tenant_id="default", legacy_root=legacy, store=self.store)
        self.assertEqual(n1, 1)
        lines1 = [ln for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines1), 2)
        n2 = migrate_legacy_chat_sessions(tenant_id="default", legacy_root=legacy, store=self.store)
        self.assertEqual(n2, 0)
        lines2 = [ln for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines2), 2)


class TestChatSessionsEventLogIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.sessions_path = Path(self._td.name) / "chat_sessions.json"
        self.events_path = Path(self._td.name) / "session_events.jsonl"
        cs._migration_done = False

    def tearDown(self) -> None:
        self._td.cleanup()
        cs._migration_done = False

    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_ENABLED", True)
    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_PATH", "")
    @patch("app.config.CHAT_SESSIONS_STORE_PATH", "")
    @patch("app.chat_sessions._store_path")
    @patch("app.repositories.session_event_store._events_path")
    @patch("app.repositories.session_event_store._meta_path")
    def test_append_writes_two_events(
        self,
        mock_meta: unittest.mock.MagicMock,
        mock_ev: unittest.mock.MagicMock,
        mock_sess: unittest.mock.MagicMock,
    ) -> None:
        mock_sess.return_value = self.sessions_path
        mock_ev.return_value = self.events_path
        mock_meta.return_value = self.events_path.with_suffix(".meta.json")
        with patch("app.config.CHAT_SESSIONS_STORE_PATH", str(self.sessions_path)):
            with patch("app.config.CHAT_SESSIONS_EVENT_LOG_PATH", str(self.events_path)):
                created = cs.create_session(title="Nova")
                sid = created["id"]
                ok = cs.append_completed_turn(sid, user_text="pergunta", assistant_text="resposta")
                self.assertTrue(ok)
                lines = [ln for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                self.assertEqual(len(lines), 2)
                types = [json.loads(ln)["type"] for ln in lines]
                self.assertEqual(types, ["user_message", "assistant_message"])
                hist = cs.history_dicts_for_prepare(sid)
                self.assertEqual(
                    hist,
                    [
                        {"role": "user", "content": "pergunta"},
                        {"role": "assistant", "content": "resposta"},
                    ],
                )
                row = cs.get_session(sid)
                assert row is not None
                self.assertEqual(row["messages"], hist)

    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_ENABLED", True)
    @patch("app.chat_sessions._store_path")
    @patch("app.repositories.session_event_store._events_path")
    @patch("app.repositories.session_event_store._meta_path")
    def test_migrate_then_append(
        self,
        mock_meta: unittest.mock.MagicMock,
        mock_ev: unittest.mock.MagicMock,
        mock_sess: unittest.mock.MagicMock,
    ) -> None:
        mock_sess.return_value = self.sessions_path
        mock_ev.return_value = self.events_path
        mock_meta.return_value = self.events_path.with_suffix(".meta.json")
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.sessions_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "sessions": [
                        {
                            "id": sid,
                            "title": "Old",
                            "pinned": False,
                            "updated_at": "2026-05-16T10:00:00+00:00",
                            "messages": [{"role": "user", "content": "legacy"}],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cs._migration_done = False
        hist = cs.history_dicts_for_prepare(sid)
        self.assertEqual(hist, [{"role": "user", "content": "legacy"}])
        cs.append_completed_turn(sid, user_text="novo", assistant_text="ok")
        hist2 = cs.history_dicts_for_prepare(sid)
        self.assertEqual(len(hist2), 3)
        self.assertEqual(hist2[-2]["content"], "novo")


if __name__ == "__main__":
    unittest.main()
