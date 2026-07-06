"""Multi-workspace API (GET/POST /ui/workspaces)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.workspace_service import (
    _load_user_record,
    _normalize_user_record,
    _save_user_record,
    get_workspace_binding,
    ui_workspaces_put,
    WorkspacesPutRequest,
    WorkspaceEntry,
)


class TestWorkspacesAPI(unittest.TestCase):
    def test_normalize_legacy_single_binding(self) -> None:
        rec = _normalize_user_record(
            {
                "path": "/tmp/proj",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )
        self.assertEqual(len(rec["workspaces"]), 1)
        self.assertEqual(rec["workspaces"][0]["path"], "/tmp/proj")
        self.assertTrue(rec["active_workspace_id"])

    def test_put_and_get_binding_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "workspace_bindings.json"
            with patch("app.workspace_service._store_path", return_value=store), patch(
                "app.workspace_service.get_current_sub", return_value="user-1"
            ), patch("app.workspace_service.resolve_pg_tenant_id", return_value="tenant-a"), patch(
                "app.workspace_service.normalize_workspace_path_for_bind",
                side_effect=lambda p: str(Path(p).resolve()),
            ), patch(
                "app.workspace_service.git_metadata", return_value={}
            ):
                payload = WorkspacesPutRequest(
                    workspaces=[
                        WorkspaceEntry(id="ws-a", path="/tmp/a", label="a"),
                        WorkspaceEntry(id="ws-b", path="/tmp/b", label="b"),
                    ],
                    active_workspace_id="ws-a",
                )
                out = ui_workspaces_put(payload)
                self.assertTrue(out.get("ok"))
                binding = get_workspace_binding(tenant_id="tenant-a", user_id="user-1")
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertEqual(binding.get("id"), "ws-a")
                self.assertTrue(str(binding.get("path", "")).endswith("/a"))


if __name__ == "__main__":
    unittest.main()
