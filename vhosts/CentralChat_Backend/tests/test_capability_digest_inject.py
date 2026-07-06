"""Prioridade #6 — digest L0-2 opt-in no prefixo system (env + pedido/L2)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.server import AssistantTextRequest, _prepare_assistant_text_llm_inputs

# Marcadores de prefixo injectado antes do digest (Fase 11 SYSTEM + pré-injeção legacy).
_PREFIX_BEFORE_DIGEST = (
    "[POLICY_ANCHOR]",
    "[SYSTEM_BUNDLED",
    "[SYSTEM_OVERLAY]",
    "[SYS_ENV]",  # corpo canónico da pré-injeção
)


def _first_prefix_index(hist: list[dict[str, str]]) -> int:
    for i, m in enumerate(hist):
        content = m.get("content") or ""
        if any(marker in content for marker in _PREFIX_BEFORE_DIGEST):
            return i
    return -1


class TestCapabilityDigestInject(unittest.TestCase):
    @patch("app.context.assembler.record_capability_digest_injected")
    @patch("app.config.PRE_INJECTION_ENABLED", True)
    @patch("app.config.CAPABILITY_DIGEST_IN_PROMPT_ENABLED", True)
    def test_digest_after_system_prefix_before_prefs(self, mock_record: unittest.mock.MagicMock) -> None:
        p = AssistantTextRequest(text="ola", include_capability_digest=True)
        hist, *_rest = _prepare_assistant_text_llm_inputs(
            p, "rid-test", inject_host_context=False, digest_metrics_endpoint="test"
        )
        injection_meta = _rest[-1]
        self.assertGreaterEqual(len(hist), 2)
        joined = "\n".join(m.get("content", "") for m in hist[:12])
        self.assertIn("[CAPABILITY_DIGEST", joined)
        prefix_idx = _first_prefix_index(hist)
        dig_idx = next((i for i, m in enumerate(hist) if "[CAPABILITY_DIGEST" in (m.get("content") or "")), -1)
        self.assertGreaterEqual(prefix_idx, 0, "system prefix (Fase 11 ou pré-injeção) expected before digest")
        self.assertGreater(dig_idx, prefix_idx, "digest must come after system prefix blocks")
        mock_record.assert_called_once()
        self.assertTrue(injection_meta.get("capability_digest_block_applied"))

    @patch("app.context.assembler.record_capability_digest_injected")
    @patch("app.config.CAPABILITY_DIGEST_IN_PROMPT_ENABLED", False)
    def test_digest_off_when_env_disabled(self, mock_record: unittest.mock.MagicMock) -> None:
        p = AssistantTextRequest(text="ola", include_capability_digest=True)
        hist, *_rest = _prepare_assistant_text_llm_inputs(
            p, "rid-2", inject_host_context=False, digest_metrics_endpoint="test"
        )
        joined = "\n".join(m.get("content", "") for m in hist[:8])
        self.assertNotIn("[CAPABILITY_DIGEST", joined)
        mock_record.assert_not_called()
        self.assertFalse(_rest[-1].get("capability_digest_block_applied"))


if __name__ == "__main__":
    unittest.main()
