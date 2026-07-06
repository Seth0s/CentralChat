"""Tests for workspace_guard (Phase 1)."""

from __future__ import annotations

import os
import tempfile
import unittest

from app.shared.workspace_guard import WorkspaceGuardError, normalize_workspace_root, resolve_workspace_path


class TestWorkspaceGuard(unittest.TestCase):
    def test_resolve_relative_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = normalize_workspace_root(tmp)
            child = os.path.join(root, "src", "main.py")
            os.makedirs(os.path.dirname(child), exist_ok=True)
            with open(child, "w", encoding="utf-8") as fh:
                fh.write("x")
            resolved = resolve_workspace_path(workspace_root=root, path="src/main.py")
            self.assertEqual(resolved, child)

    def test_reject_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = normalize_workspace_root(tmp)
            with self.assertRaises(WorkspaceGuardError) as ctx:
                resolve_workspace_path(workspace_root=root, path="../etc/passwd")
            self.assertEqual(ctx.exception.code, "path_outside_workspace")


if __name__ == "__main__":
    unittest.main()
