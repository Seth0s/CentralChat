"""
Fase I+ / L4 — propriedades leves do parse (sem hypothesis; loops determinísticos).

Garante que o parser não rebenta com entradas válidas construídas e que o gate
parse pode repetir-se em volume (smoke de carga leve).
"""
from __future__ import annotations

import json
import random
import unittest

from app.tool_loop import parse_agent_tool_response

from tests.golden_l4_parse_cases import GOLDEN_PARSE_CASES


class TestPhaseLPropertyParse(unittest.TestCase):
    def test_parse_random_final_strings_never_raises(self) -> None:
        rng = random.Random(42)
        for i in range(400):
            body = rng.choice(
                [
                    "ascii",
                    "café_日本語",
                    "\n\t\r",
                    '"' * 20,
                    "\\" * 8,
                    "{" * 3 + "}" * 3,
                ]
            )
            noise = "".join(rng.choice("abc \n\t") for _ in range(rng.randint(0, 12)))
            final_val = f"{noise}{i}{body}{noise}"
            raw = json.dumps({"final": final_val, "tool_calls": []}, ensure_ascii=False)
            try:
                f, calls, ok = parse_agent_tool_response(raw)
            except Exception as exc:  # pragma: no cover
                self.fail(f"parse raised on iter {i}: {exc!r}")
            self.assertTrue(ok, f"iter {i}")
            self.assertEqual(f, final_val.strip() or None)
            self.assertEqual(calls, [])

    def test_golden_parse_load_smoke_many_passes(self) -> None:
        """Repete toda a bateria golden parse (rápido) — regressão + smoke de carga."""
        repeats = 120
        for _ in range(repeats):
            for case in GOLDEN_PARSE_CASES:
                raw = str(case["raw"])
                expect_ok = bool(case["expect_ok"])
                f, calls, ok = parse_agent_tool_response(raw)
                self.assertEqual(ok, expect_ok, case["id"])
                if not expect_ok:
                    continue
                if "expect_final" in case:
                    self.assertEqual(f, case["expect_final"], case["id"])
                if "expect_tool_names" in case:
                    names = [str(c.get("name", "")) for c in calls]
                    self.assertEqual(names, list(case["expect_tool_names"]), case["id"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
