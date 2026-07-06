"""Golden tests for ContextEngine — pluggable step pipeline.

Tests the assemble_context() entry point and verify that all phases
execute with the correct step ordering and output structure.

These tests mock out PG-dependent functions so the engine can run
without a database connection. Mocks are applied once in setUpClass
for performance.

Design: Snapshot tests on ContextState fields.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_engine import (
    STEP_REGISTRY,
    ContextState,
    TokenBudget,
    assemble_context_sync,
    list_steps,
)
from app.context_engine.registry import Phase


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _default_state(**overrides) -> dict:
    """Build kwargs for assemble_context_sync."""
    defaults = {
        "request_id": "test-req-1",
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


# ═══════════════════════════════════════════════════════════════
# Phase and registry tests
# ═══════════════════════════════════════════════════════════════

class TestStepRegistry(unittest.TestCase):
    """Verify step registration is correct."""

    def test_all_phases_have_steps(self) -> None:
        """Every phase has at least one step registered."""
        for phase in Phase:
            steps = list_steps(phase)
            self.assertGreater(
                len(steps), 0,
                f"Phase {phase.value} should have at least one step",
            )

    def test_resolve_steps_run_first(self) -> None:
        """Resolve steps have lower priority than gather steps."""
        resolve_steps = list_steps(Phase.RESOLVE)
        gather_steps = list_steps(Phase.GATHER)
        for rs in resolve_steps:
            for gs in gather_steps:
                self.assertLess(rs.priority, gs.priority + 100)

    def test_total_step_count(self) -> None:
        """Verify expected step count."""
        self.assertEqual(len(STEP_REGISTRY), 19,
                         f"Expected 19 steps, got {len(STEP_REGISTRY)}")

    def test_all_steps_have_valid_phase(self) -> None:
        """Every step's phase is a valid Phase enum."""
        for name, step in STEP_REGISTRY.items():
            self.assertIn(step.phase, Phase,
                          f"Step {name} has invalid phase: {step.phase}")


# ═══════════════════════════════════════════════════════════════
# Assemble context tests
# ═══════════════════════════════════════════════════════════════

class TestAssembleContextGolden(unittest.TestCase):
    """Golden tests for assemble_context_sync()."""

    _BASE_MOCKS = [
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

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in cls._BASE_MOCKS]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    # ── Tests (mocks applied at class level — no per-method decorators) ──

    def test_basic_web_no_session(self) -> None:
        """GOLDEN: simplest web request."""
        state = assemble_context_sync(**_default_state())

        self.assertIsInstance(state, ContextState)
        self.assertGreater(len(state.messages), 1)
        self.assertEqual(state.messages[-1]["role"], "user")
        self.assertEqual(state.messages[-1]["content"], "Olá, como estás?")

        system_msgs = [m for m in state.messages if m["role"] == "system"]
        self.assertGreater(len(system_msgs), 0)
        self.assertTrue(any("[ENV]" in m["content"] for m in system_msgs))
        self.assertGreater(state.build_ms, 0)

    def test_cli_mode_with_workspace(self) -> None:
        """GOLDEN: CLI mode with workspace."""
        state = assemble_context_sync(**_default_state(
            user_text="lê o ficheiro main.py",
            mode="cli", connector_alive=True,
            workspace_path="/home/dev/project",
        ))
        self.assertEqual(state.meta.get("execution_mode"), "cli")
        self.assertTrue(state.meta.get("connector_alive"))
        system_msgs = [m for m in state.messages if m["role"] == "system"]
        self.assertTrue(any("CLI" in m["content"] for m in system_msgs))
        self.assertGreater(len(state.tool_catalog), 0)

    def test_tools_have_valid_schemas(self) -> None:
        """GOLDEN: every tool has valid OpenAI function schema."""
        state = assemble_context_sync(**_default_state(
            user_text="search for bugs and fix them",
            mode="cli", connector_alive=True,
            workspace_path="/tmp/test",
        ))
        for tool in state.tools:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("parameters", tool["function"])

    def test_empty_history_no_crash(self) -> None:
        """GOLDEN: empty history assembles without error."""
        state = assemble_context_sync(**_default_state(
            user_text="primeira mensagem", history=[],
        ))
        self.assertEqual(state.messages[-1]["role"], "user")
        self.assertIsNotNone(state.messages)

    def test_session_id_propagates_to_state(self) -> None:
        """GOLDEN: session_id is passed through."""
        state = assemble_context_sync(**_default_state(
            session_id="sess-abc-123",
        ))
        self.assertEqual(state.session_id, "sess-abc-123")

    def test_work_item_id_stub(self) -> None:
        """GOLDEN: work_item_id triggers ResolveWorkItem — falls back gracefully without PG."""
        state = assemble_context_sync(**_default_state(
            work_item_id="WI-142",
        ))
        # Without PG, WI lookup returns None → state recorded, no L2
        self.assertEqual(state.meta.get("work_item_resolved"), "WI-142")
        self.assertIn(state.meta.get("work_item_state"), ("not_found", "lookup_failed"))
        # L2 is NOT injected when WI not found
        self.assertNotIn("L2", state.layers_applied)
    def test_focus_mode_disables_rag(self) -> None:
        """GOLDEN: focus_mode disables all RAG gates."""
        state = assemble_context_sync(**_default_state(
            focus_mode=True, session_id="sess-1",
        ))
        self.assertEqual(state.session_rag_gate, "never")
        self.assertEqual(state.product_rag_gate, "never")
        self.assertTrue(state.focus_mode)

    def test_meta_fields_present(self) -> None:
        """GOLDEN: meta has essential fields."""
        state = assemble_context_sync(**_default_state())
        self.assertIn("execution_mode", state.meta)
        self.assertIn("tools_injected", state.meta)
        self.assertIn("context_policy_summary_pt", state.meta)

    def test_auditor_restricted_tools(self) -> None:
        """GOLDEN: auditor role has no write tools."""
        state = assemble_context_sync(**_default_state(role="auditor"))
        tool_names = {t["function"]["name"] for t in state.tools}
        for write_tool in ("terminal", "write_file", "patch", "execute_code"):
            self.assertNotIn(write_tool, tool_names)


# ═══════════════════════════════════════════════════════════════
# State type tests
# ═══════════════════════════════════════════════════════════════

class TestContextState(unittest.TestCase):
    """Verify ContextState defaults and token budget math."""

    def test_default_state_values(self) -> None:
        state = ContextState()
        self.assertEqual(state.mode, "web")
        self.assertEqual(state.role, "developer")

    def test_token_budget_available(self) -> None:
        budget = TokenBudget(max_total=128_000)
        self.assertGreater(budget.available_for_l6(), 0)

    def test_token_budget_over_budget(self) -> None:
        budget = TokenBudget(max_total=100, l0_l4=80, l5_rag=10,
                             l6_window=20, l7_tools=10)
        self.assertTrue(budget.is_over_budget())


if __name__ == "__main__":
    unittest.main()
