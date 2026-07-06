"""B2.3/B2.4 — Golden policy + compliance pack tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.shared.policy_engine import evaluate_tool_policy
from tests.golden_policy_cases import GOLDEN_COMPLIANCE_PACK_CASES, GOLDEN_POLICY_CASES


class TestPolicyGolden(unittest.TestCase):
    def test_default_policy_matrix(self) -> None:
        for case in GOLDEN_POLICY_CASES:
            with self.subTest(case_id=case["id"]):
                res = evaluate_tool_policy(
                    str(case["tool"]),
                    dict(case.get("args") or {}),
                    tenant_id="default",
                )
                if case.get("allowed"):
                    self.assertTrue(res.allowed, res.message_pt)
                else:
                    self.assertFalse(res.allowed, case["id"])
                    if case.get("error_code"):
                        self.assertEqual(res.error_code, case["error_code"])

    def test_break_glass_precedence_over_deny(self) -> None:
        with patch("app.shared.break_glass.break_glass_allows_path") as mock_bg:
            mock_bg.return_value = {"id": "g1", "tenant_id": "default", "user_id": "u1", "path_pattern": "**/.env*"}
            with patch("app.shared.break_glass.record_break_glass_use"):
                res = evaluate_tool_policy("read_file", {"path": ".env"}, tenant_id="default")
        self.assertTrue(res.allowed)

    def test_compliance_pack_cases(self) -> None:
        from app.shared.compliance_packs import _COMPLIANCE_PACKS

        for case in GOLDEN_COMPLIANCE_PACK_CASES:
            pack = _COMPLIANCE_PACKS.get(str(case["pack_id"]))
            assert pack is not None
            with self.subTest(case=case):
                with patch(
                    "app.shared.policy_engine._load_tenant_policies",
                    return_value=pack["policies"],
                ):
                    res = evaluate_tool_policy(
                        str(case["tool"]),
                        dict(case.get("args") or {}),
                        tenant_id="default",
                    )
                if case.get("allowed"):
                    self.assertTrue(res.allowed)
                else:
                    self.assertFalse(res.allowed)


if __name__ == "__main__":
    unittest.main()
