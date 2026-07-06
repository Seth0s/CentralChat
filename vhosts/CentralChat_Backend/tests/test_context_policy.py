"""Golden tests for ContextPolicy resolution."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_policy import (
    AutoGate,
    ContextPolicy,
    build_policy_summary_pt,
    resolve_policy,
)


class TestAutoGate(unittest.TestCase):
    def test_never_is_not_automatic(self) -> None:
        self.assertFalse(AutoGate.NEVER.is_automatic())

    def test_always_if_session_is_automatic(self) -> None:
        self.assertTrue(AutoGate.ALWAYS_IF_SESSION.is_automatic())

    def test_semantic_gate_is_automatic(self) -> None:
        self.assertTrue(AutoGate.SEMANTIC_GATE.is_automatic())

    def test_values_are_strings(self) -> None:
        """AutoGate values are strings for JSON serialization."""
        for gate in AutoGate:
            self.assertIsInstance(gate.value, str)


class TestResolvePolicy(unittest.TestCase):
    """Golden tests for resolve_policy() behavior."""

    def test_default_web_no_session(self) -> None:
        """No session → session_rag=NEVER, memory=NEVER."""
        policy = resolve_policy(
            tenant_id="default",
            execution_mode="web",
            chat_session_id=None,
        )
        self.assertEqual(policy.session_rag, AutoGate.NEVER)
        self.assertEqual(policy.memory_recall, AutoGate.NEVER)
        self.assertEqual(policy.document_rag, AutoGate.NEVER)
        self.assertFalse(policy.focus_mode)

    def test_with_session_enables_session_rag(self) -> None:
        """Session present → session_rag=ALWAYS_IF_SESSION, memory=SEMANTIC_GATE."""
        policy = resolve_policy(
            tenant_id="default",
            execution_mode="web",
            chat_session_id="sess-abc-123",
        )
        self.assertEqual(policy.session_rag, AutoGate.ALWAYS_IF_SESSION)
        self.assertEqual(policy.memory_recall, AutoGate.SEMANTIC_GATE)

    def test_with_active_document_enables_document_rag(self) -> None:
        """Active document → document_rag=IF_ACTIVE_DOC."""
        policy = resolve_policy(
            tenant_id="default",
            execution_mode="web",
            active_document_id="doc-42",
        )
        self.assertEqual(policy.document_rag, AutoGate.IF_ACTIVE_DOC)

    def test_focus_mode_disables_all_rag(self) -> None:
        """Focus mode → all gates = NEVER."""
        policy = resolve_policy(
            tenant_id="default",
            execution_mode="web",
            chat_session_id="sess-abc",
            active_document_id="doc-1",
            force_focus=True,
        )
        self.assertEqual(policy.session_rag, AutoGate.NEVER)
        self.assertEqual(policy.memory_recall, AutoGate.NEVER)
        self.assertEqual(policy.document_rag, AutoGate.NEVER)
        self.assertEqual(policy.product_rag, AutoGate.NEVER)
        self.assertEqual(policy.playbook, AutoGate.NEVER)
        self.assertTrue(policy.focus_mode)
        self.assertFalse(policy.dlp_enabled)

    def test_product_rag_default_enabled(self) -> None:
        """Product RAG defaults to INTENT_GATE (env CENTRAL_PRODUCT_RAG_ENABLED=1)."""
        policy = resolve_policy(tenant_id="default")
        self.assertEqual(policy.product_rag, AutoGate.INTENT_GATE)

    def test_playbook_default_keyword_gate(self) -> None:
        """Playbook defaults to KEYWORD_GATE."""
        policy = resolve_policy(tenant_id="default")
        self.assertEqual(policy.playbook, AutoGate.KEYWORD_GATE)

    def test_auditor_role_restricts_tools(self) -> None:
        """Auditor role → allowlist excludes write tools."""
        policy = resolve_policy(tenant_id="default", role="auditor")
        allowlist = policy.role_tool_allowlist
        self.assertGreater(len(allowlist), 0)
        # Auditors must NOT have write tools
        for write_tool in ("terminal", "write_file", "patch", "execute_code"):
            self.assertNotIn(write_tool, allowlist,
                             f"auditor should not have {write_tool}")

    def test_reviewer_role_restricts_tools(self) -> None:
        """Reviewer role → read-only tools."""
        policy = resolve_policy(tenant_id="default", role="reviewer")
        allowlist = policy.role_tool_allowlist
        # Reviewer gets read_file, search_files
        self.assertIn("read_file", allowlist)
        self.assertIn("search_files", allowlist)
        # But NOT write tools
        self.assertNotIn("write_file", allowlist)
        self.assertNotIn("terminal", allowlist)

    def test_developer_role_has_no_restrictions(self) -> None:
        """Developer role → empty allowlist (all tools allowed)."""
        policy = resolve_policy(tenant_id="default", role="developer")
        self.assertEqual(len(policy.role_tool_allowlist), 0)

    def test_deprecated_flags_captured(self) -> None:
        """Legacy flags are recorded but do not affect gate decisions."""
        policy = resolve_policy(
            tenant_id="default",
            include_long_session_memory=True,
            include_memory_recall=True,
            include_document_rag=True,
            include_playbook=True,
            include_host_context=True,
            include_capability_digest=True,
        )
        deprecated = policy._deprecated_flags
        self.assertTrue(deprecated["include_long_session_memory"])
        self.assertTrue(deprecated["include_memory_recall"])
        self.assertTrue(deprecated["include_document_rag"])

        # But gates are NOT driven by flags — session_rag depends on session_id
        self.assertEqual(policy.session_rag, AutoGate.NEVER,
                         "No session → session_rag should be NEVER regardless of flag")

    def test_work_item_id_propagated(self) -> None:
        """Work item ID flows into policy."""
        policy = resolve_policy(
            tenant_id="default",
            work_item_id="WI-142",
        )
        self.assertEqual(policy.work_item_id, "WI-142")

    def test_pre_injection_path_when_enabled(self) -> None:
        """Pre-injection path set when env enabled."""
        with patch("app.config.PRE_INJECTION_ENABLED", True):
            with patch("app.config.PRE_INJECTION_FILE_PATH", "/etc/prompt.txt"):
                policy = resolve_policy(tenant_id="default")
                self.assertEqual(policy.pre_injection_path, "/etc/prompt.txt")

    def test_pre_injection_disabled_in_focus(self) -> None:
        """Pre-injection disabled in focus mode even when env enabled."""
        with patch("app.config.PRE_INJECTION_ENABLED", True):
            with patch("app.config.PRE_INJECTION_FILE_PATH", "/etc/prompt.txt"):
                policy = resolve_policy(tenant_id="default", force_focus=True)
                self.assertIsNone(policy.pre_injection_path)


class TestContextPolicyDefaults(unittest.TestCase):
    """Verify default values are sensible."""

    def test_default_max_tokens(self) -> None:
        policy = ContextPolicy()
        self.assertEqual(policy.max_context_tokens, 128_000)

    def test_default_rag_budget(self) -> None:
        policy = ContextPolicy()
        self.assertEqual(policy.rag_char_budget, 6_000)

    def test_default_verbatim_tail(self) -> None:
        policy = ContextPolicy()
        self.assertEqual(policy.verbatim_tail_messages, 20)

    def test_default_dlp_enabled(self) -> None:
        policy = ContextPolicy()
        self.assertTrue(policy.dlp_enabled)

    def test_default_no_focus(self) -> None:
        policy = ContextPolicy()
        self.assertFalse(policy.focus_mode)


class TestBuildPolicySummary(unittest.TestCase):
    """UI trace summary strings."""

    def test_focus_mode_summary(self) -> None:
        policy = resolve_policy(force_focus=True)
        summary = build_policy_summary_pt(policy)
        self.assertIn("Modo foco", summary)

    def test_session_summary_includes_rag_info(self) -> None:
        policy = resolve_policy(chat_session_id="sess-1")
        summary = build_policy_summary_pt(policy)
        self.assertIn("RAG sessão", summary)
        self.assertIn("automático", summary)

    def test_auditor_summary_includes_role(self) -> None:
        policy = resolve_policy(role="auditor")
        summary = build_policy_summary_pt(policy)
        self.assertIn("auditor", summary.lower() or " ")
        # If no role mention, at least non-empty
        self.assertGreater(len(summary), 0)

    def test_minimal_context_summary(self) -> None:
        """No session, no doc → minimal context."""
        policy = resolve_policy(chat_session_id=None, active_document_id=None)
        summary = build_policy_summary_pt(policy)
        # Should at least mention DLP or minimal
        self.assertGreater(len(summary), 0)


if __name__ == "__main__":
    unittest.main()
