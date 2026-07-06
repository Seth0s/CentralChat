"""Fase 8 — SSE `done.schema_version` (envelope) e cancelamento ao disconnect."""
from __future__ import annotations

import json
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

app = None
TestClient = None
ASSISTANT_SSE_DONE_SCHEMA_VERSION = 1
try:
    from fastapi.testclient import TestClient as _TestClient

    from app.server import ASSISTANT_SSE_DONE_SCHEMA_VERSION as _VER
    from app.server import app as _app

    ASSISTANT_SSE_DONE_SCHEMA_VERSION = int(_VER)
    TestClient = _TestClient
    app = _app
except ImportError:  # pragma: no cover
    pass


def _parse_sse_event_payload(body: str, event: str) -> dict | None:
    pattern = rf"event: {re.escape(event)}\r?\ndata: (.+?)(?:\r?\n\r?\n|$)"
    for m in re.finditer(pattern, body, re.DOTALL):
        raw = m.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _parse_sse_done_payload(body: str) -> dict | None:
    for m in re.finditer(r"event: done\ndata: (.+?)(?:\r?\n\r?\n|$)", body, re.DOTALL):
        raw = m.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


@unittest.skipUnless(app is not None and TestClient is not None, "FastAPI app em falta")
class TestAssistantTextStreamPhase8(unittest.TestCase):
    _payload: dict = {
        "text": "fase 8 stream",
        "history": [],
        "use_agent_tools": False,
        "include_host_context": False,
        "include_memory_recall": False,
        "include_long_session_memory": False,
        "include_playbook": False,
    }

    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    def test_done_includes_envelope_schema_version(
        self, mock_hybrid: MagicMock, _audit: MagicMock
    ) -> None:
        def _lines():
            yield json.dumps({"e": "token", "d": "Hi"}, ensure_ascii=False)
            yield json.dumps({"e": "done"}, ensure_ascii=False)

        mock_hybrid.return_value = _lines()
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        done = _parse_sse_done_payload(body)
        self.assertIsNotNone(done)
        assert done is not None
        self.assertEqual(done.get("schema_version"), ASSISTANT_SSE_DONE_SCHEMA_VERSION)
        segs = done.get("composer_segments")
        self.assertIsInstance(segs, list)
        self.assertEqual(segs[0].get("schema_version"), 1)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    @patch.object(Request, "is_disconnected", new_callable=AsyncMock)
    def test_disconnect_skips_done_after_first_token(
        self, mock_disc: AsyncMock, mock_hybrid: MagicMock, _audit: MagicMock
    ) -> None:
        def _lines():
            yield json.dumps({"e": "token", "d": "x"}, ensure_ascii=False)
            yield json.dumps({"e": "token", "d": "y"}, ensure_ascii=False)
            yield json.dumps({"e": "done"}, ensure_ascii=False)

        mock_hybrid.return_value = _lines()
        mock_disc.side_effect = [False, False, True]
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: token", body)
        self.assertNotIn("event: done", body)
        cancelled = any(
            c.args and isinstance(c.args[0], dict) and c.args[0].get("event") == "assistant_text_stream_cancelled"
            for c in _audit.call_args_list
        )
        self.assertTrue(cancelled, _audit.call_args_list)

    @patch("app.repositories.chat_sessions_repository.append_completed_turn")
    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    def test_llm_error_no_done_no_session_persist(
        self,
        mock_hybrid: MagicMock,
        _audit: MagicMock,
        mock_append: MagicMock,
    ) -> None:
        def _lines():
            yield json.dumps({"e": "error", "message": "router timeout"}, ensure_ascii=False)

        mock_hybrid.return_value = _lines()
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertNotIn("event: done", body)
        err = _parse_sse_event_payload(body, "error")
        self.assertIsNotNone(err)
        assert err is not None
        self.assertEqual(err.get("code"), "llm_stream_error")
        self.assertTrue(err.get("turn_not_persisted"))
        self.assertIn("não foi guardado", str(err.get("user_message_pt") or "").lower())
        self.assertIn("type", err)
        self.assertIn("status", err)
        mock_append.assert_not_called()

    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    def test_empty_reply_no_done(
        self,
        mock_hybrid: MagicMock,
        _audit: MagicMock,
    ) -> None:
        def _lines():
            yield json.dumps({"e": "done"}, ensure_ascii=False)

        mock_hybrid.return_value = _lines()
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload) as resp:
            body = resp.read().decode("utf-8")
        self.assertNotIn("event: done", body)
        err = _parse_sse_event_payload(body, "error")
        self.assertIsNotNone(err)
        assert err is not None
        self.assertEqual(err.get("code"), "empty_reply")


if __name__ == "__main__":
    unittest.main()
