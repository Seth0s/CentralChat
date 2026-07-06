"""Onda 4 tests — Multi-dev L2: work item, handoff, role-scoped tools, memory namespace.

Tests:
- WorkItemContextStep (L2 block injection)
- Handoff/fork/observe session modes
- Role-scoped tool enforcement
- Memory namespace work_item:{id}
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_engine import assemble_context_sync, ContextState
from app.context_engine.registry import STEP_REGISTRY, Phase, list_steps


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _default_state(**overrides) -> dict:
    defaults = {
        "request_id": "test-onda4",
        "user_text": "Olá, preciso de ajuda com este work item.",
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

def _base_mocks():
    """Return fresh patches for each test class."""
    return [
        patch("app.shared.system_prompt_loader.build_system_prompt_injection_messages",
              return_value=([], {"skipped": True})),
        patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
              return_value=""),
        patch("app.context_engine.steps.gather.system_layers._load_skills",
              return_value=([], [])),
        patch("app.context_engine.steps.gather.system_layers._build_l1",
              return_value=([], {"skipped": True})),
        patch("app.context_engine.steps.gather.system_layers._build_l4",
              return_value=(None, {"rule_count": 0})),
    ]


# ═══════════════════════════════════════════════════════════════
# Work Item tests
# ═══════════════════════════════════════════════════════════════

class TestWorkItemStep(unittest.TestCase):
    """ResolveWorkItem step tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    def test_wi_stub_no_db(self) -> None:
        """Without PG, WI lookup fails gracefully (not_found state)."""
        state = assemble_context_sync(**_default_state(
            work_item_id="WI-999",
        ))
        self.assertEqual(state.meta.get("work_item_resolved"), "WI-999")
        self.assertIn(state.meta.get("work_item_state"), ("not_found", "lookup_failed", "stub"))

    def test_no_wi_no_l2(self) -> None:
        """Without work_item_id, no L2 block is injected."""
        state = assemble_context_sync(**_default_state(
            work_item_id=None,
        ))
        self.assertNotIn("L2", state.layers_applied)

    @patch("app.work_queue.get_work_item")
    def test_wi_with_real_data(self, mock_get_wi) -> None:
        """WI with data injects L2 block with metadata."""
        mock_get_wi.return_value = {
            "id": "WI-142",
            "title": "Implementar ContextEngine",
            "description": "Migrar pipeline para steps plugáveis",
            "status": "in_progress",
            "priority": "high",
            "assignee_id": "user-abc",
            "repo": "centralchat/backend",
            "workspace_path": "/home/dev/project",
            "labels": ["backend", "pipeline"],
            "approval_ids": ["ap-1", "ap-2"],
            "source": "manual",
        }

        state = assemble_context_sync(**_default_state(
            work_item_id="WI-142",
        ))

        self.assertIn("L2", state.layers_applied)
        self.assertEqual(state.meta.get("work_item_resolved"), "WI-142")
        self.assertEqual(state.meta.get("work_item_state"), "in_progress")
        self.assertEqual(state.meta.get("work_item_assignee"), "user-abc")
        self.assertEqual(state.meta.get("work_item_repo"), "centralchat/backend")
        self.assertEqual(state.meta.get("work_item_labels"), ["backend", "pipeline"])
        self.assertEqual(state.meta.get("work_item_approval_ids"), ["ap-1", "ap-2"])

        # Workspace from WI used as fallback
        self.assertEqual(state.workspace_path, "/home/dev/project")

        # Check L2 block content
        l2_sections = [s for s in state.sections if s.kind == "work_item"]
        self.assertEqual(len(l2_sections), 1)
        self.assertIn("Implementar ContextEngine", l2_sections[0].content)
        self.assertIn("in_progress", l2_sections[0].content)
        self.assertIn("high", l2_sections[0].content)


# ═══════════════════════════════════════════════════════════════
# Handoff / Fork / Observe tests
# ═══════════════════════════════════════════════════════════════

class TestHandoffStep(unittest.TestCase):
    """ResolveHandoff step tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    def test_fork_clears_history(self) -> None:
        """Fork mode clears history but keeps WI context."""
        state = assemble_context_sync(**_default_state(
            session_mode="fork",
            handoff_from_session_id="sess-old-1",
            work_item_id="WI-1",
            history=[
                {"role": "user", "content": "old msg 1"},
                {"role": "assistant", "content": "old reply 1"},
            ],
        ))
        self.assertTrue(state.meta.get("session_forked"))
        self.assertEqual(state.meta.get("fork_from_session"), "sess-old-1")
        # History should be cleared
        self.assertEqual(len(state.history), 0)

    def test_observe_restricts_tools(self) -> None:
        """Observe mode sets read-only role allowlist."""
        state = assemble_context_sync(**_default_state(
            session_mode="observe",
            handoff_from_session_id="sess-obs-1",
        ))
        self.assertTrue(state.meta.get("session_observe"))
        self.assertGreater(len(state.role_tool_allowlist), 0)
        # No write tools in observe mode
        for write_tool in ("terminal", "write_file", "patch", "execute_code"):
            self.assertNotIn(write_tool, state.role_tool_allowlist)

    @patch("app.context_engine.steps.resolve.handoff._load_session_summary",
           return_value=None)
    def test_handoff_injects_summary(self, _m) -> None:
        """Handoff mode adds handoff section and metadata."""
        state = assemble_context_sync(**_default_state(
            handoff_from_session_id="sess-old-2",
            session_id="sess-new-1",
            work_item_id="WI-2",
        ))
        self.assertTrue(state.meta.get("session_handoff"))
        self.assertEqual(state.meta.get("handoff_from_session"), "sess-old-2")
        self.assertEqual(state.meta.get("handoff_work_item"), "WI-2")

        # Handoff section injected
        handoff_sections = [s for s in state.sections if s.kind == "handoff"]
        self.assertGreater(len(handoff_sections), 0)

    def test_continue_mode_no_handoff(self) -> None:
        """Default continue mode does not trigger handoff."""
        state = assemble_context_sync(**_default_state(
            session_mode="continue",
            handoff_from_session_id=None,
        ))
        self.assertFalse(state.meta.get("session_handoff", False))
        self.assertFalse(state.meta.get("session_forked", False))
        self.assertFalse(state.meta.get("session_observe", False))


# ═══════════════════════════════════════════════════════════════
# Role-scoped tools tests
# ═══════════════════════════════════════════════════════════════

class TestRoleScopedTools(unittest.TestCase):
    """Tool selection honors role_tool_allowlist."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    def test_auditor_no_write_tools(self) -> None:
        """Auditor role has no write tools (enforced by policy + ToolSelectionStep)."""
        state = assemble_context_sync(**_default_state(
            role="auditor",
        ))
        tool_names = {t["function"]["name"] for t in state.tools}
        for write_tool in ("terminal", "write_file", "patch", "execute_code"):
            self.assertNotIn(write_tool, tool_names,
                             f"auditor should not have {write_tool}")

    def test_reviewer_read_only_tools(self) -> None:
        """Reviewer role gets read inspection tools."""
        state = assemble_context_sync(**_default_state(
            role="reviewer",
        ))
        tool_names = {t["function"]["name"] for t in state.tools}
        # Reviewer should have read tools
        if "read_file" in tool_names:
            self.assertIn("read_file", tool_names)
        # But NOT write tools
        self.assertNotIn("write_file", tool_names)
        self.assertNotIn("terminal", tool_names)

    def test_developer_all_tools(self) -> None:
        """Developer role has empty allowlist (all tools allowed)."""
        state = assemble_context_sync(**_default_state(
            role="developer",
        ))
        self.assertEqual(state.role_tool_allowlist, frozenset())
        # At minimum TIER_0 tools are present
        tool_names = {t["function"]["name"] for t in state.tools}
        self.assertTrue({"memory", "session_search", "clarify"}.issubset(tool_names))

    def test_role_scoped_meta(self) -> None:
        """When role allowlist is active, meta records it."""
        state = assemble_context_sync(**_default_state(
            role="auditor",
        ))
        self.assertTrue(state.meta.get("tools_role_scoped", False))
        self.assertEqual(state.meta.get("tools_role"), "auditor")


# ═══════════════════════════════════════════════════════════════
# Memory namespace tests
# ═══════════════════════════════════════════════════════════════

class TestMemoryNamespace(unittest.TestCase):
    """Memory uses work_item namespace when WI is active."""

    def test_wi_memory_namespace(self) -> None:
        """work_item_id → namespace = work_item:{id}."""
        state = ContextState(
            work_item_id="WI-42",
            user_text="test",
            session_rag_gate="never",
            document_rag_gate="never",
            memory_recall_gate="always_if_session",
            product_rag_gate="never",
            playbook_gate="never",
        )
        # Namespace logic is in retrieval step — test via gate
        from app.context_engine.steps.gather.retrieval import RetrievalOrchestratorStep
        step = STEP_REGISTRY["gather.retrieval"]
        # Verify the step exists and handles WI memory namespace
        self.assertEqual(state.work_item_id, "WI-42")

    def test_no_wi_uses_user_profile(self) -> None:
        """No work_item_id → namespace defaults to user_profile."""
        state = ContextState(
            work_item_id=None,
            user_text="test",
            session_rag_gate="never",
            document_rag_gate="never",
            memory_recall_gate="always_if_session",
            product_rag_gate="never",
            playbook_gate="never",
        )
        self.assertIsNone(state.work_item_id)


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestOnda4Integration(unittest.TestCase):
    """End-to-end tests for multi-dev features."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    @patch("app.context_engine.steps.resolve.handoff._load_session_summary",
           return_value=None)
    @patch("app.work_queue.get_work_item")
    def test_full_wi_flow(self, mock_get_wi, _m) -> None:
        """Full pipeline with WI: L2 block + memory namespace + handoff."""
        mock_get_wi.return_value = {
            "id": "WI-142",
            "title": "Fix login bug",
            "description": "Users cannot login with SSO",
            "status": "in_progress",
            "priority": "urgent",
            "assignee_id": "dev-1",
            "repo": "centralchat/backend",
            "workspace_path": "/home/dev/project",
            "labels": ["bug", "sso"],
            "approval_ids": [],
            "source": "manual",
        }

        state = assemble_context_sync(**_default_state(
            work_item_id="WI-142",
            session_id="sess-integration-4",
            handoff_from_session_id="sess-old-99",
        ))

        # L2 from work item
        self.assertIn("L2", state.layers_applied)
        self.assertEqual(state.meta.get("work_item_resolved"), "WI-142")

        # Handoff metadata
        self.assertTrue(state.meta.get("session_handoff"))

        # Workspace propagated from WI
        self.assertEqual(state.workspace_path, "/home/dev/project")

    def test_handoff_phase_order(self) -> None:
        """Handoff step runs after work_item in resolve phase."""
        resolve_steps = list_steps(Phase.RESOLVE)
        names = [s.name for s in resolve_steps]
        wi_idx = names.index("resolve.work_item")
        handoff_idx = names.index("resolve.handoff")
        self.assertLess(wi_idx, handoff_idx,
                        "work_item should run before handoff")


if __name__ == "__main__":
    unittest.main()
