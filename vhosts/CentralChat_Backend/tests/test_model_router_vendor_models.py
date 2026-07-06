"""Normalização de IDs do catálogo do model-router (intersecção com allowlist)."""
from __future__ import annotations

import unittest

from app.model_router_vendor_models import _row_from_item


class TestVendorModelNormalization(unittest.TestCase):
    def test_preserves_openrouter_style_google_prefix(self) -> None:
        row = _row_from_item({"id": "google/gemini-2.0-flash-001", "label": "Gemini 2.0 Flash"})
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "google/gemini-2.0-flash-001")

    def test_strips_models_prefix_only(self) -> None:
        row = _row_from_item({"id": "models/gemini-1.5-pro", "label": "x"})
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "gemini-1.5-pro")

    def test_preserves_openai_and_anthropic_ids(self) -> None:
        for mid in ("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"):
            row = _row_from_item({"id": mid, "label": mid})
            self.assertIsNotNone(row)
            self.assertEqual(row["id"], mid)


if __name__ == "__main__":
    unittest.main()
