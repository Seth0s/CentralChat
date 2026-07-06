"""Session surface FSM — clarify interrupts and reconnect snapshot (Fase 2b)."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import app.session_surface_service as ss
import app.sessions as sessions


class SessionSurfaceServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._sessions_path = self._root / "chat_sessions.json"
        self._env = patch.object(ss, "CENTRAL_ROOT", str(self._root))
        self._env.start()
        self._store = patch.object(sessions, "CHAT_SESSIONS_EVENT_LOG_ENABLED", False)
        self._store.start()
        self._spath = patch.object(sessions, "_store_path")
        self._spath.start().return_value = self._sessions_path

    def tearDown(self) -> None:
        self._spath.stop()
        self._store.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _create_session(self, title: str = "Test") -> str:
        row = sessions.create_session(title=title)
        return str(row["id"])

    def test_clarify_interrupt_and_respond(self) -> None:
        sid = self._create_session()
        reg = ss.register_clarify_interrupt(
            session_id=sid,
            question="Qual opção?",
            choices=["A", "B"],
            request_id="req-1",
        )
        self.assertEqual(ss.get_session_phase(sid), "waiting_clarify")
        interrupt_id = str(reg["interrupt_id"])
        snap = ss.build_surface_snapshot(sid)
        assert snap is not None
        self.assertEqual(snap["session_phase"], "waiting_clarify")
        self.assertIsInstance(snap.get("interrupt"), dict)

        out = ss.respond_interrupt_http(sid, interrupt_id, choice="A", custom=None)
        self.assertTrue(out["ok"])
        self.assertEqual(out["response_text"], "A")
        self.assertEqual(ss.get_session_phase(sid), "streaming")
        self.assertIsNone(ss.build_surface_snapshot(sid).get("interrupt"))

    def test_pending_approval_cleared_by_approval_id(self) -> None:
        sid = self._create_session()
        aid = str(uuid.uuid4())
        ss.register_pending_approval(session_id=sid, approval_id=aid, summary="patch foo")
        self.assertEqual(ss.get_session_phase(sid), "waiting_approval")
        ss.clear_pending_approval_by_approval_id(aid)
        self.assertEqual(ss.get_session_phase(sid), "idle")
        snap = ss.build_surface_snapshot(sid)
        assert snap is not None
        self.assertIsNone(snap.get("pending_approval"))

    def test_surface_snapshot_messages(self) -> None:
        sid = self._create_session("Com histórico")
        sessions.append_completed_turn(sid, user_text="olá", assistant_text="oi")
        snap = ss.build_surface_snapshot(sid)
        assert snap is not None
        msgs = snap.get("messages")
        self.assertIsInstance(msgs, list)
        self.assertGreaterEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
