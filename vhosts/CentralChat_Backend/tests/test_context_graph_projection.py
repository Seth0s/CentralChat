"""Phase 7 — ContextGraphProjection from session events."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.context.graph_projection import ContextGraphProjection
from app.context.types import SessionEvent, SessionEventType
from app.multislot_context import apply_multislot_to_compacted_history


def _ev(
    *,
    etype: SessionEventType,
    content: str = "",
    slot: int | None = None,
    extra: dict | None = None,
    eid: str = "e1",
) -> SessionEvent:
    payload: dict = {"content": content}
    if slot is not None:
        payload["slot"] = slot
    if extra:
        payload.update(extra)
    return SessionEvent(
        tenant_id="default",
        session_id="12345678-abcd-ef01",
        event_type=etype,
        payload=payload,
        ts=datetime.now(timezone.utc),
        event_id=eid,
    )


class TestContextGraphProjection(unittest.TestCase):
    def test_rebuild_transcript_chronological_with_slots(self) -> None:
        events = [
            _ev(etype=SessionEventType.USER_MESSAGE, content="A", slot=1, eid="e1"),
            _ev(etype=SessionEventType.ASSISTANT_MESSAGE, content="B", slot=1, eid="e2"),
            _ev(etype=SessionEventType.USER_MESSAGE, content="C", slot=2, eid="e3"),
        ]
        graph = ContextGraphProjection().rebuild(
            events,
            slot_graph={"version": 2, "edges": [{"slot_a": 1, "slot_b": 2}]},
            default_slot=1,
        )
        self.assertEqual(graph.widget_slot_graph_version, 2)
        self.assertEqual(len(graph.slot_edges), 1)
        self.assertEqual(len(graph.transcript_messages()), 3)
        self.assertIn("slot:2:", graph.transcript_messages()[-1]["content"])
        self.assertEqual(len(graph.messages_by_slot[1]), 2)
        self.assertEqual(len(graph.messages_by_slot[2]), 1)

    def test_canvas_and_terminal_nodes(self) -> None:
        events = [
            _ev(
                etype=SessionEventType.CANVAS_PATCH,
                slot=1,
                extra={"ok": True, "artifact_id": "art-1"},
                eid="c1",
            ),
            _ev(
                etype=SessionEventType.TERMINAL_OUTPUT,
                slot=1,
                extra={"stdout": "hello"},
                eid="t1",
            ),
        ]
        graph = ContextGraphProjection().rebuild(events, slot_graph={"version": 0, "edges": []})
        self.assertEqual(len(graph.workspace_snippets), 2)
        kinds = {s.kind for s in graph.workspace_snippets}
        self.assertIn("canvas_patch", kinds)
        self.assertIn("terminal_output", kinds)

    def test_multislot_parity_with_graph_transcript(self) -> None:
        events = [
            _ev(etype=SessionEventType.USER_MESSAGE, content="active", slot=1, eid="u1"),
            _ev(etype=SessionEventType.ASSISTANT_MESSAGE, content="ok", slot=1, eid="a1"),
            _ev(etype=SessionEventType.USER_MESSAGE, content="neighbor", slot=2, eid="u2"),
        ]
        graph = ContextGraphProjection().rebuild(
            events,
            slot_graph={"version": 1, "edges": [{"slot_a": 1, "slot_b": 2}]},
        )
        hist = graph.transcript_messages()
        out, meta = apply_multislot_to_compacted_history(
            compacted_history=hist,
            active_slot=1,
            neighbor_slots=[2],
            neighbor_max_messages=5,
            aggregate_max_chars=50_000,
            first_turn=False,
            first_turn_include_neighbors=True,
        )
        self.assertEqual(len(out), 3)
        self.assertNotIn("omitted_non_neighbor_slots", meta)

    def test_rebuild_deterministic_from_same_events(self) -> None:
        events = [
            _ev(etype=SessionEventType.USER_MESSAGE, content="x", slot=3, eid="a"),
            _ev(etype=SessionEventType.ASSISTANT_MESSAGE, content="y", slot=3, eid="b"),
        ]
        g1 = ContextGraphProjection().rebuild(events, slot_graph={"version": 0, "edges": []})
        g2 = ContextGraphProjection().rebuild(events, slot_graph={"version": 0, "edges": []})
        self.assertEqual(g1.transcript_messages(), g2.transcript_messages())
        self.assertEqual(g1.audit_dict()["node_count"], g2.audit_dict()["node_count"])


if __name__ == "__main__":
    unittest.main()
