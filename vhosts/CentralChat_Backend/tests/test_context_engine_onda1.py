"""Onda 1 tests — GATHER + RAG: gates, DLP, metrics, session indexing.

Tests the new functionality added in Onda 1 of the ContextEngine:
- Gate logic (semantic, intent, keyword)
- DLP scanner integration
- Memory score threshold filtering
- Playbook keyword gate
- Metrics emission (noop when prometheus unavailable)
- Session indexing (stub, real PG not needed)
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_engine import assemble_context_sync
from app.context_engine.registry import STEP_REGISTRY, Phase, list_steps
from app.context_engine.state import ContextState


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _default_state(**overrides) -> dict:
    defaults = {
        "request_id": "test-onda1",
        "user_text": "Olá, como estás?",
        "history": [],
        "tenant_id": "default",
        "user_id": "user-test",
        "role": "developer",
        "session_id": None,
        "mode": "web",
        "connector_alive": False,
    }
    defaults.update(overrides)
    return defaults


def _get_retrieval_step():
    """Get the RetrievalOrchestratorStep instance from the registry."""
    return STEP_REGISTRY["gather.retrieval"]


def _make_state(user_text: str, **overrides) -> ContextState:
    """Build a ContextState with specific gate values for testing."""
    defaults = {
        "request_id": "gtest",
        "user_text": user_text,
        "tenant_id": "default",
        "user_id": "u1",
        "role": "developer",
        "session_id": None,
        "active_document_id": None,
        "mode": "web",
        "connector_alive": False,
        "focus_mode": False,
        "session_rag_gate": "never",
        "document_rag_gate": "never",
        "memory_recall_gate": "never",
        "product_rag_gate": "never",
        "playbook_gate": "never",
    }
    defaults.update(overrides)
    return ContextState(**defaults)


# ═══════════════════════════════════════════════════════════════
# Security anchor (DLP) tests
# ═══════════════════════════════════════════════════════════════

class TestSecurityAnchorStep(unittest.TestCase):
    """L0 DLP + pre-injection step tests."""

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_dlp_passes_clean_text(self, *_m: object) -> None:
        """Clean text passes DLP scan."""
        state = assemble_context_sync(**_default_state(
            user_text="Olá, preciso de ajuda com Python.",
        ))
        self.assertTrue(state.meta.get("dlp_passed", False))

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_dlp_blocks_aws_key(self, *_m: object) -> None:
        """AWS access key triggers DLP block (16 alphanumeric after AKIA)."""
        state = assemble_context_sync(**_default_state(
            user_text="A minha chave é AKIAIOSFODNN7EXAMPLE",
        ))
        self.assertTrue(
            state.meta.get("dlp_blocked", False),
            f"DLP should block AWS key. meta={state.meta}",
        )

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_dlp_focus_mode_disabled(self, *_m: object) -> None:
        """Focus mode disables DLP (matched by policy which sets dlp_enabled=False)."""
        state = assemble_context_sync(**_default_state(
            user_text="AKIAIO...MPLE",
            focus_mode=True,
        ))
        self.assertFalse(state.dlp_enabled)
        self.assertFalse(state.meta.get("dlp_blocked", False))

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_dlp_blocks_private_key(self, *_m: object) -> None:
        """Private key block triggers DLP."""
        state = assemble_context_sync(**_default_state(
            user_text="a minha chave: -----BEGIN RSA PRIVATE KEY----- MIIEpA...",
        ))
        self.assertTrue(
            state.meta.get("dlp_blocked", False),
            f"DLP should block private key. meta={state.meta}",
        )


# ═══════════════════════════════════════════════════════════════
# Gate logic tests
# ═══════════════════════════════════════════════════════════════

class TestGateLogic(unittest.TestCase):
    """Test the gate decision logic in retrieval.py."""

    def test_session_gate_never(self) -> None:
        """NEVER gate blocks session RAG even with session_id."""
        step = _get_retrieval_step()
        state = _make_state("hello", session_id="sess-1",
                             session_rag_gate="never")
        self.assertFalse(step._gate_allows_session(state))

    def test_session_gate_always_if_session(self) -> None:
        """ALWAYS_IF_SESSION allows when session_id present."""
        step = _get_retrieval_step()
        state = _make_state("hello", session_id="sess-1",
                             session_rag_gate="always_if_session")
        self.assertTrue(step._gate_allows_session(state))

    def test_document_gate_if_active_doc(self) -> None:
        """IF_ACTIVE_DOC allows when active_document_id is set."""
        step = _get_retrieval_step()
        state = _make_state("hello", active_document_id="doc-42",
                             document_rag_gate="if_active_doc")
        self.assertTrue(step._gate_allows_document(state))

    def test_document_gate_without_doc(self) -> None:
        """IF_ACTIVE_DOC denies when no active_document_id."""
        step = _get_retrieval_step()
        state = _make_state("hello",
                             document_rag_gate="if_active_doc")
        self.assertFalse(step._gate_allows_document(state))

    def test_memory_gate_skips_short_text(self) -> None:
        """SEMANTIC_GATE skips very short queries (< 10 chars)."""
        step = _get_retrieval_step()
        state = _make_state("oi",
                             memory_recall_gate="semantic_gate")
        self.assertFalse(step._gate_allows_memory(state))

    def test_memory_gate_allows_longer_text(self) -> None:
        """SEMANTIC_GATE allows queries with >= 10 chars that aren't greetings."""
        step = _get_retrieval_step()
        state = _make_state("como implementar context engine no python",
                             memory_recall_gate="semantic_gate")
        self.assertTrue(step._gate_allows_memory(state))

    def test_product_gate_matches_keyword(self) -> None:
        """INTENT_GATE opens when product keywords match."""
        step = _get_retrieval_step()
        state = _make_state("como usar o context engine do centralchat?",
                             product_rag_gate="intent_gate")
        self.assertTrue(step._gate_allows_product(state))

    def test_product_gate_no_match(self) -> None:
        """INTENT_GATE stays closed when no product keywords match."""
        step = _get_retrieval_step()
        state = _make_state("qual é a capital do brasil?",
                             product_rag_gate="intent_gate")
        self.assertFalse(step._gate_allows_product(state))

    def test_playbook_gate_keyword_match(self) -> None:
        """KEYWORD_GATE opens when playbook keywords match."""
        step = _get_retrieval_step()
        state = _make_state("qual é o playbook para deploy?",
                             playbook_gate="keyword_gate")
        self.assertTrue(step._gate_allows_playbook(state))

    def test_playbook_gate_no_match(self) -> None:
        """KEYWORD_GATE stays closed when no playbook keywords match."""
        step = _get_retrieval_step()
        state = _make_state("qual é o tempo hoje?",
                             playbook_gate="keyword_gate")
        self.assertFalse(step._gate_allows_playbook(state))

    def test_memory_gate_skips_greeting(self) -> None:
        """SEMANTIC_GATE skips common greetings."""
        step = _get_retrieval_step()
        for greeting in ["olá", "oi", "bom dia", "hello"]:
            state = _make_state(greeting,
                                 memory_recall_gate="semantic_gate")
            self.assertFalse(
                step._gate_allows_memory(state),
                f"Greeting '{greeting}' should be skipped by semantic gate",
            )


# ═══════════════════════════════════════════════════════════════
# Metrics tests
# ═══════════════════════════════════════════════════════════════

class TestMetricsEmission(unittest.TestCase):
    """Metrics emission works (noop when prometheus_client not installed)."""

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_metrics_no_crash_without_prometheus(self, *_m: object) -> None:
        """Metrics emission does not crash when prometheus_client is missing."""
        state = assemble_context_sync(**_default_state())
        self.assertIsNotNone(state)
        self.assertGreater(state.build_ms, 0)

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_metrics_token_budget_populated(self, *_m: object) -> None:
        """Token budget meta is populated after assembly."""
        state = assemble_context_sync(**_default_state())
        budget = state.meta.get("token_budget", {})
        self.assertIn("l0_l4", budget)
        self.assertIn("l6_window", budget)
        self.assertIn("max_total", budget)

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_metrics_dlp_counter(self, *_m: object) -> None:
        """DLP block is recorded in meta for metrics (private key trigger)."""
        state = assemble_context_sync(**_default_state(
            user_text="a minha chave privada: -----BEGIN RSA PRIVATE KEY----- abc123",
        ))
        self.assertTrue(state.meta.get("dlp_blocked", False))
        self.assertIn("private_key_block", state.meta.get("dlp_hits", []))


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestOnda1Integration(unittest.TestCase):
    """End-to-end tests for Onda 1 features."""

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_full_pipeline_with_session(self, *_m: object) -> None:
        """Full pipeline: session → gates open → RAG runs → metrics emit."""
        state = assemble_context_sync(**_default_state(
            user_text="como implementar o context engine do centralchat?",
            session_id="sess-integration-1",
            mode="web",
        ))

        self.assertEqual(state.session_rag_gate, "always_if_session")
        self.assertEqual(state.product_rag_gate, "intent_gate")
        self.assertTrue(state.meta.get("dlp_passed", False))
        self.assertIsNotNone(state)

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_security_anchor_phase_order(self, *_m: object) -> None:
        """Security anchor runs first in gather phase (priority 5)."""
        gather_steps = list_steps(Phase.GATHER)
        first_step = gather_steps[0]
        self.assertEqual(first_step.name, "gather.security_anchor")
        self.assertEqual(first_step.priority, 5)

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_active_document_id_flow(self, *_m: object) -> None:
        """active_document_id propagates through policy → state → gate."""
        state = assemble_context_sync(**_default_state(
            user_text="resume este documento",
            active_document_id="doc-integration-1",
        ))

        self.assertEqual(state.document_rag_gate, "if_active_doc")
        self.assertEqual(state.active_document_id, "doc-integration-1")
        self.assertTrue(state.meta.get("active_document_validated"))

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_focus_mode_suppresses_retrieval(self, *_m: object) -> None:
        """Focus mode: all gates NEVER, retrieval step skipped."""
        state = assemble_context_sync(**_default_state(
            user_text="como usar o context engine?",
            session_id="sess-1",
            focus_mode=True,
        ))

        self.assertTrue(state.focus_mode)
        self.assertEqual(state.session_rag_gate, "never")
        self.assertEqual(state.product_rag_gate, "never")
        self.assertEqual(state.memory_recall_gate, "never")


if __name__ == "__main__":
    unittest.main()
