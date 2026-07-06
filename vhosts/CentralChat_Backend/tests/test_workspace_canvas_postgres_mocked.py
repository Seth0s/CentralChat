"""F2 — caminho postgres do workspace com store mockado (sem DB real)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.workspace_canvas import apply_canvas_patch, manage_workspace_artifact


class TestWorkspaceCanvasPostgresMocked(unittest.TestCase):
    @patch("app.workspace_canvas.WORKSPACE_STORE_BACKEND", "postgres")
    @patch("app.workspace_store_pg.load_bucket", return_value=None)
    @patch("app.workspace_store_pg.save_bucket")
    def test_create_persists_via_save_bucket(self, mock_save: MagicMock, _mock_load: MagicMock) -> None:
        r = manage_workspace_artifact(
            "session-key-f2-01",
            {
                "action": "create",
                "title": "T",
                "artifact_type": "plain",
                "content": "body",
            },
        )
        self.assertTrue(r.get("ok"), r)
        mock_save.assert_called_once()
        _sk, bucket = mock_save.call_args[0]
        self.assertEqual(_sk, "session-key-f2-01")
        self.assertIn("artifacts", bucket)
        self.assertEqual(len(bucket["artifacts"]), 1)

    @patch("app.workspace_canvas.WORKSPACE_STORE_BACKEND", "postgres")
    @patch("app.workspace_store_pg.save_bucket")
    def test_patch_loads_and_saves(self, mock_save: MagicMock) -> None:
        aid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        existing = {
            "artifacts": {
                aid: {
                    "title": "X",
                    "artifact_type": "plain",
                    "content": "hello OLD",
                    "revision": 1,
                }
            }
        }

        def _load(_sk: str):
            return existing

        with patch("app.workspace_store_pg.load_bucket", side_effect=_load):
            r = apply_canvas_patch(
                "session-key-f2-02",
                {"artifact_id": aid, "search_block": "OLD", "replace_block": "new"},
            )
        self.assertTrue(r.get("ok"), r)
        mock_save.assert_called_once()
        _sk2, bucket2 = mock_save.call_args[0]
        self.assertEqual(_sk2, "session-key-f2-02")
        self.assertIn("new", bucket2["artifacts"][aid]["content"])


if __name__ == "__main__":
    unittest.main()
