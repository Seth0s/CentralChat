"""Fase 9 — multislot_context (grafo, particionamento, orçamento)."""
from __future__ import annotations

import unittest

from app.multislot_context import (
    apply_multislot_to_compacted_history,
    effective_active_slot,
    first_turn_from_history,
    graph_neighbors,
    partition_messages_by_slot,
)


class TestMultislotContext(unittest.TestCase):
    def test_effective_active_slot(self) -> None:
        self.assertEqual(effective_active_slot(3, 1), 3)
        self.assertEqual(effective_active_slot(None, 2), 2)

    def test_graph_neighbors_order_and_cap(self) -> None:
        edges = [{"slot_a": 1, "slot_b": 2}, {"slot_a": 2, "slot_b": 4}]
        self.assertEqual(graph_neighbors(edges, 2, 10), [1, 4])
        self.assertEqual(graph_neighbors(edges, 2, 1), [1])

    def test_partition_prefix(self) -> None:
        h = [
            {"role": "user", "content": "slot:2: Olá"},
            {"role": "user", "content": "sem prefixo"},
        ]
        b = partition_messages_by_slot(h, default_slot=1)
        self.assertEqual(b[2][0]["content"], "Olá")
        self.assertEqual(b[1][0]["content"], "sem prefixo")

    def test_omits_non_neighbor_bucket(self) -> None:
        hist = [
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "slot:1: A"},
            {"role": "user", "content": "slot:3: B"},
        ]
        out, meta = apply_multislot_to_compacted_history(
            compacted_history=hist,
            active_slot=1,
            neighbor_slots=[2],
            neighbor_max_messages=5,
            aggregate_max_chars=100_000,
            first_turn=False,
            first_turn_include_neighbors=True,
        )
        self.assertEqual(meta.get("omitted_non_neighbor_slots"), [3])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1]["content"], "A")

    def test_aggregate_truncates_neighbors_first(self) -> None:
        hist = [
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "slot:1: A"},
            {"role": "user", "content": "slot:2: BBBBB"},
            {"role": "user", "content": "slot:2: CCCCC"},
        ]
        out, meta = apply_multislot_to_compacted_history(
            compacted_history=hist,
            active_slot=1,
            neighbor_slots=[2],
            neighbor_max_messages=5,
            aggregate_max_chars=25,
            first_turn=False,
            first_turn_include_neighbors=True,
        )
        self.assertTrue(meta.get("truncated"))
        self.assertLessEqual(sum(len(m["content"]) for m in out), 25)

    def test_first_turn_skips_neighbors(self) -> None:
        hist = [{"role": "user", "content": "slot:1: x"}, {"role": "user", "content": "slot:2: y"}]
        self.assertTrue(first_turn_from_history(hist))
        out, meta = apply_multislot_to_compacted_history(
            compacted_history=hist,
            active_slot=1,
            neighbor_slots=[2],
            neighbor_max_messages=5,
            aggregate_max_chars=10_000,
            first_turn=True,
            first_turn_include_neighbors=False,
        )
        self.assertTrue(meta.get("first_turn_neighbors_skipped"))
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
