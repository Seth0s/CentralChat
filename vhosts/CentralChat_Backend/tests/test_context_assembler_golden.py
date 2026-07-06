"""Phase 1 — golden parity for ContextAssembler vs legacy prepare path."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.context.assembler import ContextAssembler
from app.context.session_view import SessionView
from app.server import AssistantTextRequest, ChatMessage, _prepare_assistant_text_llm_inputs

_FIXTURES = Path(__file__).parent / "fixtures" / "context_assembler"


def _history_snapshot(history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"role": m.get("role"), "content": m.get("content")} for m in history]


def _meta_snapshot(meta: dict) -> dict:
    keys = (
        "pre_injection_applied",
        "capability_digest_block_applied",
        "preferences_system_message_count",
        "host_context_block_applied",
        "memory_recall_system_applied",
        "document_rag_applied",
        "playbook_block_applied",
        "system_prompt_bundled_applied",
        "l8_router_extract",
    )
    out = {k: meta.get(k) for k in keys if k in meta}
    if "l8_router_extract" in out and isinstance(out["l8_router_extract"], dict):
        slim = out["l8_router_extract"]
        out["l8_router_extract"] = {
            k: slim.get(k)
            for k in (
                "prefix_len",
                "tail_messages_before",
                "tail_messages_after",
                "chars_total_after",
            )
        }
    return out


class TestContextAssemblerGolden(unittest.TestCase):
    @patch("app.config.CENTRAL_FOCUS_MODE", True)
    @patch("app.config.PRE_INJECTION_ENABLED", True)
    @patch("app.config.CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED", False)
    def test_focus_mode_minimal_history(self) -> None:
        p = AssistantTextRequest(
            text="ola",
            history=[
                ChatMessage(role="user", content="u1"),
                ChatMessage(role="assistant", content="a1"),
            ],
        )
        hist, stats, truncated, recall, meta = _prepare_assistant_text_llm_inputs(
            p, "rid-golden-1", inject_host_context=False
        )
        self.assertFalse(truncated)
        self.assertEqual(recall, 0)
        self.assertFalse(stats.compacted)
        roles = [m["role"] for m in hist]
        self.assertIn("user", roles)
        self.assertFalse(meta.get("memory_recall_system_applied"))
        self.assertFalse(meta.get("host_context_block_applied"))

    @patch("app.config.CAPABILITY_DIGEST_IN_PROMPT_ENABLED", True)
    @patch("app.config.CENTRAL_FOCUS_MODE", False)
    @patch("app.config.PRE_INJECTION_ENABLED", True)
    @patch("app.config.CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED", False)
    @patch("app.context.assembler.record_capability_digest_injected")
    def test_assembler_matches_prepare_wrapper(self, _mock_digest: MagicMock) -> None:
        p = AssistantTextRequest(text="teste digest", include_capability_digest=True)
        via_server = _prepare_assistant_text_llm_inputs(
            p, "rid-parity", inject_host_context=False, digest_metrics_endpoint="test"
        )
        asm = ContextAssembler().build(
            p,
            SessionView(),
            "rid-parity",
            inject_host_context=False,
            digest_metrics_endpoint="test",
        )
        self.assertEqual(_history_snapshot(via_server[0]), _history_snapshot(asm.injected_history))
        self.assertEqual(via_server[1], asm.ctx_stats)
        self.assertEqual(via_server[2], asm.session_truncated)
        self.assertEqual(via_server[3], asm.recall_count)
        self.assertEqual(_meta_snapshot(via_server[4]), _meta_snapshot(asm.injection_meta))
        self.assertEqual(len(asm.package.sections), len([s for s in asm.package.sections if s.content]))
        self.assertIsNotNone(asm.package.token_accounting)
        self.assertIn("l8_router_extract", asm.injection_meta)

    @patch("app.config.CENTRAL_FOCUS_MODE", True)
    def test_package_history_matches_injected(self) -> None:
        p = AssistantTextRequest(text="hi")
        asm = ContextAssembler().build(
            p, SessionView(), "rid-pkg", inject_host_context=False
        )
        self.assertEqual(
            tuple(asm.injected_history),
            asm.package.history,
        )


class TestContextAssemblerFixtures(unittest.TestCase):
    """Optional fixture files for regression (written on first run if missing)."""

    @patch("app.config.CENTRAL_FOCUS_MODE", True)
    def test_write_or_load_focus_fixture(self) -> None:
        _FIXTURES.mkdir(parents=True, exist_ok=True)
        path = _FIXTURES / "focus_mode_minimal.json"
        p = AssistantTextRequest(text="fixture")
        hist, *_rest = _prepare_assistant_text_llm_inputs(p, "rid-fix", inject_host_context=False)
        payload = {
            "history": _history_snapshot(hist),
            "meta": _meta_snapshot(_rest[-1]),
        }
        if not path.is_file():
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["history"], payload["history"])


if __name__ == "__main__":
    unittest.main()
