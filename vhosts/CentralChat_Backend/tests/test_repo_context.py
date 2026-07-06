"""Git repo_context helpers."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.shared.repo_context import collect_git_metadata, format_repo_context_block


class TestRepoContext(unittest.TestCase):
    def test_non_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = collect_git_metadata(tmp)
            self.assertFalse(meta["is_git"])
            block = format_repo_context_block(workspace_path=tmp, git_meta=meta)
            self.assertIn("[WORKSPACE L2]", block)
            self.assertIn("not_a_git_repository", block)

    @patch("app.shared.repo_context.subprocess.run")
    def test_git_repo_formats_commits_and_dirty(self, mock_run: object) -> None:
        def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            if "branch" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "main\n", "")
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, " M src/a.py\n?? b.txt\n", "")
            if "log" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "abc123 init\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")

        mock_run.side_effect = fake_run  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as tmp:
            git_dir = __import__("pathlib").Path(tmp) / ".git"
            git_dir.mkdir()
            meta = collect_git_metadata(tmp)
            self.assertTrue(meta["is_git"])
            self.assertEqual(meta["branch"], "main")
            self.assertEqual(meta["dirty_count"], 2)
            block = format_repo_context_block(workspace_path=tmp, git_meta=meta)
            self.assertIn("[REPO_CONTEXT]", block)
            self.assertIn("abc123", block)


if __name__ == "__main__":
    unittest.main()
