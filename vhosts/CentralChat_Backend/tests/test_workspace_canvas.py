"""Testes T2 — workspace canvas multi-artefacto por request_id."""
from __future__ import annotations

import unittest

from app.workspace_canvas import apply_canvas_patch, manage_workspace_artifact


class WorkspaceCanvasTest(unittest.TestCase):
    def test_create_then_patch(self) -> None:
        rid = "test-req-canvas-a"
        r1 = manage_workspace_artifact(
            rid,
            {
                "action": "create",
                "title": "Notas",
                "artifact_type": "plain",
                "content": "hello OLD world",
            },
        )
        self.assertTrue(r1.get("ok"))
        self.assertEqual(r1.get("revision"), 1)
        self.assertIn("artifact_id", r1)
        aid = str(r1["artifact_id"])
        self.assertIn("canvas", r1)
        self.assertEqual(r1["canvas"]["title"], "Notas")
        r2 = apply_canvas_patch(
            rid,
            {"artifact_id": aid, "search_block": "OLD", "replace_block": "new"},
        )
        self.assertTrue(r2.get("ok"))
        self.assertEqual(r2["canvas"]["content"], "hello new world")

    def test_patch_legacy_omit_artifact_id_when_single(self) -> None:
        rid = "test-legacy-single"
        manage_workspace_artifact(
            rid,
            {"action": "create", "title": "Só um", "artifact_type": "plain", "content": "alpha BETA"},
        )
        r = apply_canvas_patch(
            rid,
            {"search_block": "BETA", "replace_block": "gamma"},
        )
        self.assertTrue(r.get("ok"))
        self.assertEqual(r["canvas"]["content"], "alpha gamma")

    def test_patch_omit_id_fails_when_multiple_artifacts(self) -> None:
        rid = "test-multi-no-id"
        manage_workspace_artifact(
            rid,
            {"action": "create", "title": "A", "artifact_type": "plain", "content": "x"},
        )
        manage_workspace_artifact(
            rid,
            {"action": "create", "title": "B", "artifact_type": "plain", "content": "y"},
        )
        r = apply_canvas_patch(
            rid,
            {"search_block": "x", "replace_block": "z"},
        )
        self.assertFalse(r.get("ok"))
        self.assertEqual(r.get("error"), "ambiguous_artifact")

    def test_create_default_title(self) -> None:
        rid = "test-req-canvas-title"
        r = manage_workspace_artifact(
            rid,
            {"action": "create", "artifact_type": "plain", "content": "x"},
        )
        self.assertTrue(r.get("ok"))
        self.assertEqual(r["canvas"]["title"], "Artefacto")

    def test_patch_ambiguous(self) -> None:
        rid = "test-req-canvas-b"
        r0 = manage_workspace_artifact(
            rid,
            {"action": "create", "title": "A", "artifact_type": "plain", "content": "aa aa"},
        )
        aid = str(r0["artifact_id"])
        r = apply_canvas_patch(
            rid,
            {"artifact_id": aid, "search_block": "aa", "replace_block": "b"},
        )
        self.assertFalse(r.get("ok"))
        self.assertEqual(r.get("error"), "ambiguous_search")

    def test_patch_no_artifact(self) -> None:
        rid2 = "empty-canvas-req"
        r = apply_canvas_patch(
            rid2,
            {"search_block": "x", "replace_block": "y"},
        )
        self.assertFalse(r.get("ok"))
        self.assertEqual(r.get("error"), "unknown_artifact")

    def test_patch_unknown_id(self) -> None:
        rid = "test-bad-id"
        manage_workspace_artifact(
            rid,
            {"action": "create", "artifact_type": "plain", "content": "z"},
        )
        r = apply_canvas_patch(
            rid,
            {
                "artifact_id": "00000000-0000-4000-8000-000000000099",
                "search_block": "z",
                "replace_block": "w",
            },
        )
        self.assertFalse(r.get("ok"))
        self.assertEqual(r.get("error"), "no_artifact")

    def test_two_artifacts_same_request(self) -> None:
        rid = "test-multi"
        r1 = manage_workspace_artifact(
            rid,
            {"action": "create", "title": "Um", "artifact_type": "plain", "content": "one"},
        )
        r2 = manage_workspace_artifact(
            rid,
            {"action": "create", "title": "Dois", "artifact_type": "plain", "content": "two"},
        )
        self.assertTrue(r1.get("ok") and r2.get("ok"))
        self.assertNotEqual(r1["artifact_id"], r2["artifact_id"])

    def test_write_ctx_metadata_and_group(self) -> None:
        rid = "f10-meta"
        edges = [{"slot_a": 1, "slot_b": 2}, {"slot_a": 2, "slot_b": 3}]
        ctx = {
            "enforce_slot_write": False,
            "active_slot": 1,
            "default_slot": 1,
            "edges": edges,
        }
        r = manage_workspace_artifact(
            rid,
            {"action": "create", "title": "T", "artifact_type": "plain", "content": "c"},
            write_ctx=ctx,
        )
        self.assertTrue(r.get("ok"))
        c = r.get("canvas") or {}
        self.assertEqual(c.get("schema_version"), 1)
        self.assertEqual(c.get("slot"), 1)
        self.assertEqual(c.get("group_id"), "1_2_3")

    def test_g6_write_forbidden_other_slot(self) -> None:
        rid = "f10-g6"
        ctx1 = {"enforce_slot_write": True, "active_slot": 1, "default_slot": 1, "edges": []}
        ctx2 = {"enforce_slot_write": True, "active_slot": 2, "default_slot": 1, "edges": []}
        r1 = manage_workspace_artifact(
            rid,
            {"action": "create", "title": "A", "artifact_type": "plain", "content": "hello"},
            write_ctx=ctx1,
        )
        self.assertTrue(r1.get("ok"))
        aid = str(r1["artifact_id"])
        r2 = apply_canvas_patch(
            rid,
            {"artifact_id": aid, "search_block": "hello", "replace_block": "bye"},
            write_ctx=ctx2,
        )
        self.assertFalse(r2.get("ok"))
        self.assertEqual(r2.get("error"), "canvas_write_forbidden")


if __name__ == "__main__":
    unittest.main()
