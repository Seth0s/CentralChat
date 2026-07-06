"""Perfis UI A/B/C vs model-router."""
from __future__ import annotations

import unittest

from app.profiles import router_profile_for_agent_tools, router_profile_for_ui_profile


class TestRouterProfileMapping(unittest.TestCase):
    def test_a_to_eco(self) -> None:
        self.assertEqual(router_profile_for_ui_profile("A"), "eco")

    def test_b_to_balanced(self) -> None:
        self.assertEqual(router_profile_for_ui_profile("B"), "balanced")

    def test_c_to_quality(self) -> None:
        self.assertEqual(router_profile_for_ui_profile("C"), "quality")

    def test_lowercase_ok(self) -> None:
        self.assertEqual(router_profile_for_ui_profile("a"), "eco")

    def test_unknown_falls_back_to_balanced(self) -> None:
        self.assertEqual(router_profile_for_ui_profile("Z"), "balanced")
        self.assertEqual(router_profile_for_ui_profile(""), "balanced")

    def test_agent_tools_force_balanced_from_eco(self) -> None:
        self.assertEqual(router_profile_for_agent_tools("eco"), "balanced")
        self.assertEqual(router_profile_for_agent_tools("local_eco"), "balanced")
        self.assertEqual(router_profile_for_agent_tools("balanced"), "balanced")
        self.assertEqual(router_profile_for_agent_tools("quality"), "quality")


if __name__ == "__main__":
    unittest.main()
