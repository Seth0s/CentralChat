"""ADR-016 — effective context cap for brain."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.inference_context import effective_inference_context_cap


class TestInferenceContext(unittest.TestCase):
    def test_product_cap_default(self) -> None:
        with patch("app.config.CENTRAL_CONTEXT_WINDOW_CAP", 200_000):
            self.assertEqual(effective_inference_context_cap(None), 200_000)
            self.assertEqual(
                effective_inference_context_cap("deepseek/deepseek-v4-flash"),
                200_000,
            )

    def test_known_small_model_bounded(self) -> None:
        with patch("app.config.CENTRAL_CONTEXT_WINDOW_CAP", 200_000):
            self.assertEqual(
                effective_inference_context_cap("openai/gpt-4o-mini"),
                128_000,
            )


if __name__ == "__main__":
    unittest.main()
