"""Fase 10 — componente conexa e group_id (G6)."""
from __future__ import annotations

import unittest

from app.canvas_write_context import connected_component_slots, group_id_from_edges


class TestCanvasWriteContext(unittest.TestCase):
    def test_connected_chain(self) -> None:
        edges = [{"slot_a": 1, "slot_b": 2}, {"slot_a": 2, "slot_b": 3}]
        self.assertEqual(connected_component_slots(edges, 1), [1, 2, 3])
        self.assertEqual(connected_component_slots(edges, 3), [1, 2, 3])
        self.assertEqual(connected_component_slots(edges, 4), [4])

    def test_group_id(self) -> None:
        edges = [{"slot_a": 1, "slot_b": 2}]
        self.assertEqual(group_id_from_edges(edges, 1), "1_2")
        self.assertEqual(group_id_from_edges([], 3), "3")


if __name__ == "__main__":
    unittest.main()
