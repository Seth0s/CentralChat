"""L3 — playbook local + feedback (store + RAG léxico)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import playbook_store as ps


class TestPlaybookStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.playbook_path = Path(self._td.name) / "playbook.json"
        self.feedback_path = Path(self._td.name) / "assistant_playbook_feedback.json"

    def tearDown(self) -> None:
        self._td.cleanup()

    def _patch_paths(self):
        return patch.object(ps, "PLAYBOOK_STORE_PATH", str(self.playbook_path))

    def test_add_list_retrieve(self) -> None:
        with self._patch_paths(), patch.object(ps, "PLAYBOOK_FEATURE_ENABLED", True):
            e = ps.add_playbook_entry_manual(
                title="CPU no host",
                body="Para métricas use get_host_summary com limit razoável.",
                tags=["cpu", "p0"],
                ttl_days=365,
            )
            self.assertTrue(e["id"])
            meta = ps.list_playbook_entries_meta()
            self.assertEqual(len(meta), 1)
            self.assertEqual(meta[0]["title"], "CPU no host")
            block = ps.build_playbook_context_block(query="Quero ver cpu e memória do host")
            self.assertIsNotNone(block)
            assert block is not None
            self.assertIn("CPU no host", block)
            self.assertIn("get_host_summary", block)

    def test_feedback_updates_counters(self) -> None:
        with self._patch_paths(), patch.object(ps, "PLAYBOOK_FEATURE_ENABLED", True):
            e = ps.add_playbook_entry_manual(title="t", body="corpo teste", tags=[], ttl_days=None)
            rid = "req-id-12345678"
            ps.record_assistant_feedback(request_id=rid, vote="up", playbook_snippet_id=e["id"])
            row = ps.get_playbook_entry(e["id"])
            self.assertEqual(int(row["helpful_votes"]), 1)  # type: ignore[index]
            self.assertTrue(self.feedback_path.is_file())

    def test_delete(self) -> None:
        with self._patch_paths(), patch.object(ps, "PLAYBOOK_FEATURE_ENABLED", True):
            e = ps.add_playbook_entry_manual(title="x", body="y", tags=[], ttl_days=None)
            self.assertTrue(ps.delete_playbook_entry(e["id"]))
            self.assertFalse(ps.delete_playbook_entry("missing"))

    def test_expired_not_retrieved(self) -> None:
        with self._patch_paths(), patch.object(ps, "PLAYBOOK_FEATURE_ENABLED", True):
            e = ps.add_playbook_entry_manual(title="velho", body="keyword zebraunique", tags=[], ttl_days=1)
            past = "2020-01-01T00:00:00+00:00"
            data = ps.load_playbook_store()
            for ent in data["entries"]:
                if ent["id"] == e["id"]:
                    ent["expires_at"] = past
            self.playbook_path.write_text(json.dumps(data), encoding="utf-8")
            block = ps.build_playbook_context_block(query="zebraunique")
            self.assertIsNone(block)


if __name__ == "__main__":
    unittest.main()
