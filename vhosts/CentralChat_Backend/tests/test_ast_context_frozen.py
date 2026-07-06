"""B3.4 — AST context remains frozen (no implementation in app/)."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


class TestAstContextFrozen(unittest.TestCase):
    def test_no_ast_runtime_modules(self) -> None:
        proc = subprocess.run(
            ["rg", "-l", r"ast_nodes|ask_project|/ast/", str(BACKEND / "app")],
            capture_output=True,
            text=True,
        )
        hits = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        self.assertEqual(hits, [], f"AST scope creep detected: {hits}")


if __name__ == "__main__":
    unittest.main()
