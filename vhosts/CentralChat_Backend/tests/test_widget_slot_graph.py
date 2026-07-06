"""Grafo multi-slot (simétrico)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import widget_slot_graph as wsg


class TestWidgetSlotGraph(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.path = Path(self._td.name) / "widget_slot_graph.json"

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_normalize_edges_symmetric_unique(self) -> None:
        raw = [{"slot_a": 4, "slot_b": 1}, {"slot_a": 1, "slot_b": 4}, [2, 3]]
        out = wsg.normalize_edges(raw)
        self.assertEqual(out, [{"slot_a": 1, "slot_b": 4}, {"slot_a": 2, "slot_b": 3}])

    def test_replace_version_conflict(self) -> None:
        with patch.object(wsg, "WIDGET_SLOT_GRAPH_STORE_PATH", str(self.path)):
            self.path.write_text(json.dumps({"version": 2, "edges": []}), encoding="utf-8")
            self.assertIsNone(wsg.replace_widget_slot_graph(expected_version=1, edges=[]))

    def test_replace_ok(self) -> None:
        with patch.object(wsg, "WIDGET_SLOT_GRAPH_STORE_PATH", str(self.path)):
            st = wsg.replace_widget_slot_graph(expected_version=0, edges=[{"slot_a": 1, "slot_b": 4}])
        self.assertIsNotNone(st)
        assert st is not None
        self.assertEqual(st["version"], 1)
        self.assertEqual(st["edges"], [{"slot_a": 1, "slot_b": 4}])


if __name__ == "__main__":
    unittest.main()
