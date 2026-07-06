"""ADR-016 — L8 stream fallback chain (model_override hops)."""
from __future__ import annotations

import unittest

from app.l8_pipeline_policy import build_stream_fallback_attempts, clear_l8_pipeline_policy_cache


class TestL8FallbackAdr16(unittest.TestCase):
    def tearDown(self) -> None:
        clear_l8_pipeline_policy_cache()

    def test_default_chain_includes_adr_model_overrides(self) -> None:
        attempts = build_stream_fallback_attempts("cloud_openai", "qwen/qwen3.5-flash-02-23")
        self.assertGreaterEqual(len(attempts), 3)
        self.assertEqual(attempts[0][1], "qwen/qwen3.5-flash-02-23")
        overrides = [mo for _p, mo, _n in attempts if mo]
        self.assertIn("deepseek/deepseek-v4-flash", overrides)
        self.assertIn("anthropic/claude-sonnet-4.6", overrides)

    def test_primary_preserved_as_first_attempt(self) -> None:
        attempts = build_stream_fallback_attempts("cloud_openai", None)
        self.assertEqual(attempts[0][0], "cloud_openai")
        self.assertIsNone(attempts[0][1])


if __name__ == "__main__":
    unittest.main()
