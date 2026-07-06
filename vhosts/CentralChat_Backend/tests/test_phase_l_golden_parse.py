"""Fase L4-1 — bateria canónica de parse JSON (sem LLM)."""
from __future__ import annotations

import unittest

from app.tool_loop import extract_json_object, parse_agent_tool_response
from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY

from tests.golden_l4_parse_cases import GOLDEN_PARSE_CASES


class TestPhaseLGoldenParse(unittest.TestCase):
    def test_all_golden_parse_cases(self) -> None:
        for case in GOLDEN_PARSE_CASES:
            cid = str(case["id"])
            with self.subTest(case_id=cid):
                raw = str(case["raw"])
                expect_ok = bool(case["expect_ok"])
                f, calls, ok = parse_agent_tool_response(raw)
                self.assertEqual(ok, expect_ok, cid)
                if not expect_ok:
                    continue
                if "expect_final" in case:
                    self.assertEqual(f, case["expect_final"], cid)
                if "expect_tool_names" in case:
                    names = [str(c.get("name", "")) for c in calls]
                    self.assertEqual(names, list(case["expect_tool_names"]), cid)  # type: ignore[arg-type]

    def test_extract_json_object_partial_dict(self) -> None:
        """extract_json_object ainda útil isoladamente (sub-JSON)."""
        d = extract_json_object('{"final": "so final"}')
        self.assertIsNotNone(d)
        self.assertEqual(d.get("final"), "so final")

    def test_valid_tool_call_host_summary_named(self) -> None:
        """Smoke explícito para regressão rápida (nome de tool canónico)."""
        raw = (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}' % TOOL_NAME_GET_HOST_SUMMARY
        )
        f, calls, ok = parse_agent_tool_response(raw)
        self.assertTrue(ok)
        self.assertIsNone(f)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("name"), TOOL_NAME_GET_HOST_SUMMARY)


if __name__ == "__main__":
    unittest.main()
