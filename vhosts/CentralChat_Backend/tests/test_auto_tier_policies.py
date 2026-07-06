"""Pacotes Auto configuráveis (Fase 6)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.auto_tier_policies import (
    auto_tier_policies_public_snapshot,
    clear_auto_tier_policies_cache,
    load_auto_tier_policies_bundle,
    pick_index_for_tier,
    pick_model_id_for_auto_tier,
)


class TestAutoTierPolicies(unittest.TestCase):
    def tearDown(self) -> None:
        clear_auto_tier_policies_cache()

    def test_default_pick_indices(self) -> None:
        pol, _ = load_auto_tier_policies_bundle(force_reload=True)
        self.assertEqual(pick_index_for_tier("economy", 3, policies=pol), 0)
        self.assertEqual(pick_index_for_tier("balanced", 3, policies=pol), 1)
        self.assertEqual(pick_index_for_tier("premium", 3, policies=pol), 2)

    def test_file_overrides_premium_pick(self) -> None:
        custom = {
            "schema_version": 2,
            "tiers": {"premium": {"pick": "first"}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(custom, f)
            path = f.name
        try:
            with patch("app.auto_tier_policies.AUTO_TIER_POLICIES_PATH", path):
                clear_auto_tier_policies_cache()
                pol, src = load_auto_tier_policies_bundle(force_reload=True)
                self.assertEqual(src, "file")
                self.assertEqual(pick_index_for_tier("premium", 5, policies=pol), 0)
                cat = [{"id": f"m{i}", "enabled": True} for i in range(5)]
                mid = pick_model_id_for_auto_tier("premium", cat)
                self.assertEqual(mid, "m0")
        finally:
            Path(path).unlink(missing_ok=True)
            clear_auto_tier_policies_cache()

    def test_public_snapshot_has_three_tiers(self) -> None:
        clear_auto_tier_policies_cache()
        snap = auto_tier_policies_public_snapshot()
        self.assertIn("tiers", snap)
        self.assertEqual(set(snap["tiers"].keys()), {"economy", "balanced", "premium"})
        self.assertIn("pick", snap["tiers"]["economy"])

    def test_adr016_dev_allowlist_auto_tiers(self) -> None:
        """ADR §15 dev allowlist (economy → premium) with default pick policies."""
        adr_dev_catalog = [
            {"id": "deepseek/deepseek-v4-flash:free", "enabled": True},
            {"id": "google/gemma-4-26b-a4b-it:free", "enabled": True},
            {"id": "openai/gpt-oss-20b:free", "enabled": True},
        ]
        clear_auto_tier_policies_cache()
        self.assertEqual(
            pick_model_id_for_auto_tier("economy", adr_dev_catalog),
            "deepseek/deepseek-v4-flash:free",
        )
        self.assertEqual(
            pick_model_id_for_auto_tier("balanced", adr_dev_catalog),
            "google/gemma-4-26b-a4b-it:free",
        )
        self.assertEqual(
            pick_model_id_for_auto_tier("premium", adr_dev_catalog),
            "openai/gpt-oss-20b:free",
        )


if __name__ == "__main__":
    unittest.main()
