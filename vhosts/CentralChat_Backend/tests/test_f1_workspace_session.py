"""F1/A1 — workspace store keyed by workspace_session_id across HTTP-correlated request_ids."""
from __future__ import annotations

import unittest

from app.tool_registry import (
    TOOL_NAME_APPLY_CANVAS_PATCH,
    TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT,
    dispatch_tool,
)


class TestF1WorkspaceSession(unittest.TestCase):
    def test_canvas_shared_across_dispatch_request_ids_with_same_workspace_store_key(self) -> None:
        sid = "f1-ws-session-integration-01"
        r1 = dispatch_tool(
            TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT,
            {
                "action": "create",
                "title": "Doc",
                "artifact_type": "plain",
                "content": "hello world",
            },
            "http-request-aaa-111",
            workspace_store_key=sid,
        )
        self.assertTrue(r1.get("ok"), r1)
        aid = str(r1.get("artifact_id", ""))
        self.assertGreater(len(aid), 8)

        r2 = dispatch_tool(
            TOOL_NAME_APPLY_CANVAS_PATCH,
            {
                "artifact_id": aid,
                "search_block": "hello",
                "replace_block": "goodbye",
            },
            "http-request-bbb-222",
            workspace_store_key=sid,
        )
        self.assertTrue(r2.get("ok"), r2)
        canvas = r2.get("canvas")
        self.assertIsInstance(canvas, dict)
        self.assertIn("goodbye", str(canvas.get("content", "")))

    def test_canvas_isolated_when_workspace_store_key_matches_request_id_only(self) -> None:
        out1 = dispatch_tool(
            TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT,
            {
                "action": "create",
                "title": "A",
                "artifact_type": "plain",
                "content": "only-a",
            },
            "req-isolated-001",
        )
        self.assertTrue(out1.get("ok"), out1)
        aid = str(out1.get("artifact_id", ""))

        out2 = dispatch_tool(
            TOOL_NAME_APPLY_CANVAS_PATCH,
            {
                "artifact_id": aid,
                "search_block": "only",
                "replace_block": "x",
            },
            "req-isolated-002",
        )
        self.assertFalse(out2.get("ok"))
        self.assertEqual(out2.get("error"), "unknown_artifact")


if __name__ == "__main__":
    unittest.main()
