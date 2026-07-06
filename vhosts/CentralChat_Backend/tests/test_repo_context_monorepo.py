"""B3.2 — repo_context on synthetic monorepo."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest

from app.shared.repo_context import collect_git_metadata, format_repo_context_block

MAX_L2_CHARS = 8000


class TestRepoContextMonorepo(unittest.TestCase):
    def test_large_repo_metadata_within_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp
            for i in range(12):
                pkg = os.path.join(root, f"packages/pkg{i}")
                os.makedirs(pkg, exist_ok=True)
                with open(os.path.join(pkg, "main.go"), "w", encoding="utf-8") as fh:
                    fh.write(f"package pkg{i}\n")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "e2e@test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "e2e"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
            for j in range(6):
                with open(os.path.join(root, f"dirty{j}.txt"), "w", encoding="utf-8") as fh:
                    fh.write("x")
            t0 = time.monotonic()
            meta = collect_git_metadata(root)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 5.0)
            self.assertLessEqual(len(meta.get("dirty_files") or []), 20)
            block = format_repo_context_block(workspace_path=root, git_meta=meta)
            self.assertIn("[REPO_CONTEXT]", block)
            self.assertLessEqual(len(block), MAX_L2_CHARS + 500)


if __name__ == "__main__":
    unittest.main()
