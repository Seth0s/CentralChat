"""OC-20 — run_dev_subprocess (ADR-011)."""

from __future__ import annotations

import shutil
import unittest

from app.dev_sandbox_runner import run_dev_subprocess


class TestDevSandboxRunner(unittest.TestCase):
    def test_rejects_empty_argv(self) -> None:
        with self.assertRaises(ValueError):
            run_dev_subprocess((), timeout_sec=1.0, cwd=None, arg0_allowlist=("/bin/",))

    def test_rejects_bad_arg0(self) -> None:
        with self.assertRaises(ValueError):
            run_dev_subprocess(
                ["/evil/bin", "x"],
                timeout_sec=1.0,
                cwd=None,
                arg0_allowlist=("/bin/",),
            )

    @unittest.skipUnless(bool(shutil.which("true")), "true binary not found")
    def test_true_runs(self) -> None:
        true_path = shutil.which("true")
        assert true_path
        out = run_dev_subprocess(
            [true_path],
            timeout_sec=2.0,
            cwd=None,
            arg0_allowlist=(true_path, "/bin/", "/usr/bin/"),
        )
        self.assertEqual(out["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
