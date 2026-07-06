"""ADR17-5 — session events for tools / client jobs + linear projection."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.context.projection import LinearTranscriptProjection
from app.context.session_events import record_client_job_session_events
from app.context.tool_event_sanitize import sanitize_tool_payload_for_event_log
from app.context.types import SessionEvent, SessionEventType
from app.repositories.session_event_store import SessionEventStore


class TestToolEventSanitize(unittest.TestCase):
    def test_truncates_large_stdout(self) -> None:
        big = "x" * 50_000
        out = sanitize_tool_payload_for_event_log({"stdout": big, "exit_code": 0})
        raw = json.dumps(out)
        self.assertLess(len(raw), 12_000)
        self.assertIn("stdout", out)

    def test_omits_binary_hint(self) -> None:
        blob = "data:image/png;base64," + ("A" * 2000)
        out = sanitize_tool_payload_for_event_log({"data": blob})
        self.assertTrue(out.get("data", {}).get("omitted") or "omitted" in str(out))


class TestClientJobSessionEvents(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.events_path = Path(self._td.name) / "session_events.jsonl"

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_ENABLED", True)
    @patch("app.repositories.session_event_store._events_path")
    def test_submit_job_result_appends_events(self, mock_ev: unittest.mock.MagicMock) -> None:
        mock_ev.return_value = self.events_path
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        job = {
            "job_id": "11111111-2222-3333-4444-555555555555",
            "tenant_id": "default",
            "session_id": sid,
            "action_id": "shell.exec",
            "status": "succeeded",
            "tool_call_id": "shell-req-1",
            "result": {"exit_code": 0, "stdout": "ok\n", "stderr": ""},
        }
        record_client_job_session_events(job=job)
        lines = [ln for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 2)
        types = {json.loads(ln)["type"] for ln in lines}
        self.assertIn("client_job_completed", types)
        self.assertIn("tool_result", types)

    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_ENABLED", True)
    @patch("app.repositories.session_event_store._events_path")
    def test_linear_projection_includes_job_completed(self, mock_ev: unittest.mock.MagicMock) -> None:
        mock_ev.return_value = self.events_path
        store = SessionEventStore()
        sid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        base = datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc)
        store.append(
            SessionEvent(
                tenant_id="default",
                session_id=sid,
                event_type=SessionEventType.USER_MESSAGE,
                payload={"content": "run ls"},
                ts=base,
            )
        )
        record_client_job_session_events(
            job={
                "job_id": "22222222-3333-4444-5555-666666666666",
                "tenant_id": "default",
                "session_id": sid,
                "action_id": "shell.exec",
                "status": "succeeded",
                "result": {"exit_code": 0, "stdout": "file.txt"},
            }
        )
        events = store.list_for_session("default", sid)
        projected = LinearTranscriptProjection().project(events)
        self.assertEqual(projected[0]["role"], "user")
        self.assertTrue(any(m["role"] == "system" and "client_job" in m["content"] for m in projected))


class TestContextAssemblerToolEventsGolden(unittest.TestCase):
    """Assembler reads event log via chat_sessions projection when session id is set."""

    @patch("app.config.CHAT_SESSIONS_EVENT_LOG_ENABLED", True)
    @patch("app.config.WIDGET_MULTI_SLOT_ENABLED", False)
    @patch("app.config.CENTRAL_FOCUS_MODE", True)
    def test_messages_for_session_includes_tool_line(self) -> None:
        from app import chat_sessions as cs

        sid = "cccccccc-dddd-eeee-ffff-000000000001"
        with patch.object(cs._store, "list_for_session") as mock_list:
            base = datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc)
            mock_list.return_value = [
                SessionEvent(
                    tenant_id="default",
                    session_id=sid,
                    event_type=SessionEventType.USER_MESSAGE,
                    payload={"content": "hi"},
                    ts=base,
                ),
                SessionEvent(
                    tenant_id="default",
                    session_id=sid,
                    event_type=SessionEventType.CLIENT_JOB_COMPLETED,
                    payload={
                        "action_id": "shell.exec",
                        "status": "succeeded",
                        "summary": "exit_code=0",
                    },
                    ts=base,
                ),
            ]
            msgs = cs._messages_for_session(sid, fallback=[])
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[1]["role"], "system")
            self.assertIn("client_job", msgs[1]["content"])
