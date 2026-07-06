"""Phase 6 — CompactionService token triggers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.context.compaction_service import CompactionService
from app.context.config import ContextSystemSettings


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class TestCompactionService(unittest.TestCase):
    def _svc(self, *, cap: int = 100_000, ratio: float = 0.75) -> CompactionService:
        settings = ContextSystemSettings(
            context_window_cap=cap,
            compact_threshold_ratio=ratio,
            reserved_output_tokens=min(2_000, cap // 5),
            reserved_injection_tokens=min(1_000, cap // 10),
        )
        return CompactionService(settings=settings)

    def test_no_compact_below_threshold(self) -> None:
        svc = self._svc()
        history = [_msg("user", "short")] * 4
        payload = MagicMock(include_long_session_memory=True, chat_session_id=None)
        result = svc.compact(
            history=history,
            request_id="r1",
            session_id=None,
            tenant_id="default",
            eco_summarizer=lambda _: "summary",
            include_long_session_memory=True,
            session_max_messages=64,
            summary_store_path="/tmp/x.json",
        )
        self.assertFalse(result.ctx_stats.compacted)
        self.assertEqual(result.compaction_meta["compaction_mode"], "none")

    @patch("app.session_summary_store.memory_db_enabled", return_value=False)
    @patch("app.context.compaction_service._schedule_async_compaction", return_value=True)
    @patch("app.context.compaction_service.get_latest_session_summary", return_value=None)
    def test_async_when_over_threshold_not_overflow(
        self,
        _latest: MagicMock,
        _sched: MagicMock,
        _db: MagicMock,
    ) -> None:
        with patch("app.config.CENTRAL_COMPACTION_SYNC_OVERFLOW_RATIO", 0.99), patch(
            "app.config.CENTRAL_COMPACT_MIN_VERBATIM_TOKENS", 50
        ):
            svc = self._svc(cap=10_000, ratio=0.75)
            chunk = "a" * 1000
            history = [_msg("user", chunk), _msg("assistant", chunk)] * 12
            summarizer = MagicMock(return_value="eco summary")
            result = svc.compact(
                history=history,
                request_id="r2",
                session_id="12345678-abcd",
                tenant_id="default",
                eco_summarizer=summarizer,
                include_long_session_memory=True,
                session_max_messages=64,
                summary_store_path="/tmp/x.json",
            )
        self.assertTrue(result.ctx_stats.compacted)
        self.assertEqual(result.compaction_meta["compaction_mode"], "async_pending")
        self.assertTrue(result.compaction_meta["async_scheduled"])
        summarizer.assert_not_called()
        self.assertGreaterEqual(result.ctx_stats.verbatim_tokens_after, 50)

    @patch("app.session_summary_store.memory_db_enabled", return_value=False)
    @patch("app.context.compaction_service._persist_summary", return_value=3)
    @patch("app.context.compaction_service.get_latest_session_summary", return_value=None)
    def test_sync_on_imminent_overflow(
        self,
        _latest: MagicMock,
        _persist: MagicMock,
        _db: MagicMock,
    ) -> None:
        with patch("app.config.CENTRAL_COMPACTION_SYNC_OVERFLOW_RATIO", 0.5), patch(
            "app.config.CENTRAL_COMPACT_MIN_VERBATIM_TOKENS", 50
        ):
            svc = self._svc(cap=2_000, ratio=0.5)
            big = "x" * 400
            history = [_msg("user", big), _msg("assistant", big)] * 40
            summarizer = MagicMock(return_value="sync summary")
            result = svc.compact(
                history=history,
                request_id="r3",
                session_id="12345678-abcd",
                tenant_id="default",
                eco_summarizer=summarizer,
                include_long_session_memory=True,
                session_max_messages=64,
                summary_store_path="/tmp/x.json",
            )
        self.assertTrue(result.ctx_stats.compacted)
        self.assertEqual(result.compaction_meta["compaction_mode"], "sync")
        summarizer.assert_called_once()
        self.assertEqual(result.compaction_meta["summary_version"], 3)
        self.assertGreaterEqual(result.ctx_stats.verbatim_tokens_after, 50)

    def test_truncated_without_long_memory(self) -> None:
        svc = self._svc()
        history = [_msg("user", "u")] * 200
        result = svc.compact(
            history=history,
            request_id="r4",
            session_id=None,
            tenant_id="default",
            eco_summarizer=lambda _: "x",
            include_long_session_memory=False,
            session_max_messages=10,
            summary_store_path="/tmp/x.json",
        )
        self.assertLess(len(result.compacted_history), len(history))
        self.assertEqual(result.compaction_meta["compaction_mode"], "truncated")


if __name__ == "__main__":
    unittest.main()
