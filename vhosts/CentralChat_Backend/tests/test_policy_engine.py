"""H1 — policy_engine path/tool/model gates."""
from __future__ import annotations

import unittest

from app.shared.policy_engine import evaluate_path_policy, evaluate_tool_policy, policies_public_snapshot


class PolicyEngineTest(unittest.TestCase):
    def test_denies_env_read(self) -> None:
        r = evaluate_path_policy("src/.env.local", mode="read", tenant_id="default")
        self.assertFalse(r.allowed)
        self.assertEqual(r.error_code, "policy_path_denied")

    def test_allows_benign_path(self) -> None:
        r = evaluate_path_policy("src/utils/helpers.py", mode="read", tenant_id="default")
        self.assertTrue(r.allowed)

    def test_terminal_denied_in_payment(self) -> None:
        r = evaluate_tool_policy(
            "terminal",
            {"cwd": "apps/payment/service"},
            tenant_id="default",
        )
        self.assertFalse(r.allowed)
        self.assertIn("policy", r.error_code or "")

    def test_public_snapshot_has_repos(self) -> None:
        snap = policies_public_snapshot(tenant_id="default")
        self.assertIn("repos", snap)
        self.assertIsInstance(snap["repos"], list)


if __name__ == "__main__":
    unittest.main()
