"""Onda 2 tests — ASSEMBLE + budget: tiktoken, SchemaTracker, unified compaction.

Tests:
- TokenCounter (tiktoken vs chars/4 fallback)
- SchemaTracker (injection, missing detection, compaction handling)
- Unified CompactionPrepStep (threshold, truncation, summarization)
- TokenBudgetStep (accurate allocation)
- PendingStateStep (approvals, WI blockers)
- ToolSelectionStep with SchemaTracker integration
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_engine import assemble_context_sync
from app.context_engine.token_counter import TokenCounter, count_tokens
from app.context_engine.schema_tracker import SchemaTracker, get_schema_tracker
from app.context_engine.state import ContextState
from app.context_engine.registry import STEP_REGISTRY


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _default_state(**overrides) -> dict:
    defaults = {
        "request_id": "test-onda2",
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
# TokenCounter tests
# ═══════════════════════════════════════════════════════════════

class TestTokenCounter(unittest.TestCase):
    """tiktoken-based token counting."""

    def test_count_basic(self) -> None:
        """Count tokens in a simple string."""
        counter = TokenCounter()
        n = counter.count("Hello, world!")
        self.assertGreater(n, 0)
        self.assertLess(n, 10)

    def test_count_empty(self) -> None:
        """Empty string returns 0 tokens."""
        counter = TokenCounter()
        self.assertEqual(counter.count(""), 0)

    def test_count_messages(self) -> None:
        """Count tokens across messages."""
        counter = TokenCounter()
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        n = counter.count_messages(msgs)
        self.assertGreater(n, 5)
        self.assertLess(n, 30)

    def test_count_tools(self) -> None:
        """Count tokens for tool schemas."""
        counter = TokenCounter()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file from disk",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        n = counter.count_tools(tools)
        self.assertGreater(n, 5)

    def test_count_empty_messages(self) -> None:
        """Empty message list returns 0."""
        counter = TokenCounter()
        self.assertEqual(counter.count_messages([]), 0)

    def test_count_empty_tools(self) -> None:
        """Empty tools list returns 0."""
        counter = TokenCounter()
        self.assertEqual(counter.count_tools([]), 0)

    def test_chars_fallback(self) -> None:
        """When tiktoken unavailable, falls back to chars/4."""
        counter = TokenCounter()
        n = counter.count("12345678")  # 8 chars
        if counter.available:
            self.assertIsInstance(n, int)
        else:
            self.assertEqual(n, 2)  # 8/4 = 2

    def test_convenience_function(self) -> None:
        """count_tokens() convenience function works."""
        n = count_tokens("test")
        self.assertGreater(n, 0)


# ═══════════════════════════════════════════════════════════════
# SchemaTracker tests
# ═══════════════════════════════════════════════════════════════

class TestSchemaTracker(unittest.TestCase):
    """Schema tracking across turns."""

    def test_mark_and_check(self) -> None:
        """Mark injected → is_present returns True."""
        tracker = SchemaTracker()
        schema = {"type": "function", "function": {"name": "test_tool", "description": "desc"}}
        tracker.mark_injected("test_tool", schema)
        self.assertTrue(tracker.is_present("test_tool", schema))

    def test_schema_change_detected(self) -> None:
        """Schema change → is_present returns False."""
        tracker = SchemaTracker()
        schema1 = {"function": {"name": "t1", "description": "v1"}}
        schema2 = {"function": {"name": "t1", "description": "v2"}}
        tracker.mark_injected("t1", schema1)
        self.assertFalse(tracker.is_present("t1", schema2))

    def test_unknown_tool_not_present(self) -> None:
        """Unknown tool → is_present returns False."""
        tracker = SchemaTracker()
        self.assertFalse(tracker.is_present("missing", {}))

    def test_get_missing(self) -> None:
        """get_missing returns tools that need injection."""
        tracker = SchemaTracker()
        tools = {
            "t1": {"function": {"name": "t1", "description": "d1"}},
            "t2": {"function": {"name": "t2", "description": "d2"}},
        }
        tracker.mark_injected("t1", tools["t1"])
        # With empty current_messages, marker won't be found → t1 also missing
        missing = tracker.get_missing(tools, [])
        self.assertIn("t2", missing)
        self.assertIn("t1", missing)  # marker not in empty messages

    def test_handle_compaction(self) -> None:
        """After compaction, missing markers are removed from tracker."""
        tracker = SchemaTracker()
        schema = {"function": {"name": "t1", "description": "d1"}}
        tracker.mark_injected("t1", schema)

        # Simulate compaction: empty messages → marker not found
        tracker.handle_compaction([])
        self.assertNotIn("t1", tracker.active)

    def test_reset(self) -> None:
        """Reset clears all tracking."""
        tracker = SchemaTracker()
        schema = {"function": {"name": "t1", "description": "d1"}}
        tracker.mark_injected("t1", schema)
        tracker.reset()
        self.assertEqual(len(tracker.active), 0)

    def test_session_tracker_reuse(self) -> None:
        """Same session_id returns same tracker."""
        t1 = get_schema_tracker("sess-abc")
        t2 = get_schema_tracker("sess-abc")
        self.assertIs(t1, t2)

    def test_no_session_returns_fresh_tracker(self) -> None:
        """No session_id returns a new tracker each time."""
        t1 = get_schema_tracker(None)
        t2 = get_schema_tracker(None)
        self.assertIsNot(t1, t2)


# ═══════════════════════════════════════════════════════════════
# Token budget step tests
# ═══════════════════════════════════════════════════════════════

class TestTokenBudgetStep(unittest.TestCase):
    """Token budget allocation with tiktoken."""

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_budget_uses_tiktoken(self, *_m: object) -> None:
        """Token budget records tiktoken availability."""
        state = assemble_context_sync(**_default_state())
        budget = state.meta.get("token_budget", {})
        self.assertIn("tiktoken_available", budget)
        self.assertIn("l0_l4", budget)
        self.assertIn("l7_tools", budget)
        self.assertIn("over_budget", budget)

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_budget_not_over_with_short_input(self, *_m: object) -> None:
        """Short input stays under budget."""
        state = assemble_context_sync(**_default_state())
        budget = state.meta.get("token_budget", {})
        self.assertFalse(budget.get("over_budget", True))


# ═══════════════════════════════════════════════════════════════
# Compaction step tests
# ═══════════════════════════════════════════════════════════════

class TestCompactionStep(unittest.TestCase):
    """Unified compaction with tiktoken."""

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_short_history_no_compaction(self, *_m: object) -> None:
        """Short history (3 messages) passes through without compaction."""
        state = assemble_context_sync(**_default_state(
            history=[
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "reply1"},
                {"role": "user", "content": "msg2"},
            ],
        ))
        self.assertFalse(state.session_truncated)
        ta = state.meta.get("token_accounting", {})
        self.assertFalse(ta.get("compacted", True))

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_long_history_compacts(self, *_m: object) -> None:
        """100 messages trigger compaction."""
        history = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"message number {i} with extra padding text to increase tokens"}
            for i in range(100)
        ]
        state = assemble_context_sync(**_default_state(
            history=history,
            session_id="sess-compact-test",
        ))
        ta = state.meta.get("token_accounting", {})
        # With 100 messages, should compact
        # (compaction might be truncation or summarization depending on token count)
        self.assertTrue(
            state.session_truncated or ta.get("compacted"),
            f"100 messages should trigger compaction. truncated={state.session_truncated} ta={ta}",
        )

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_compaction_preserves_user_text(self, *_m: object) -> None:
        """Even after compaction, the final user text is preserved."""
        history = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(65)
        ]
        state = assemble_context_sync(**_default_state(
            history=history,
            user_text="esta é a minha pergunta final",
        ))

        # User text should be the last message
        self.assertEqual(state.messages[-1]["role"], "user")
        self.assertEqual(state.messages[-1]["content"], "esta é a minha pergunta final")


# ═══════════════════════════════════════════════════════════════
# Pending state step tests
# ═══════════════════════════════════════════════════════════════

class TestPendingStateStep(unittest.TestCase):
    """Pending state injection tests."""

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_no_pending_without_session(self, *_m: object) -> None:
        """No pending state injected without session_id or work_item_id."""
        state = assemble_context_sync(**_default_state())
        self.assertFalse(state.meta.get("pending_state_injected", False))

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_pending_with_session(self, *_m: object) -> None:
        """Session triggers pending state lookup."""
        state = assemble_context_sync(**_default_state(
            session_id="sess-pending-test",
        ))
        # Should attempt lookup (may fail gracefully without PG)
        self.assertIn(
            "pending_state_injected",
            {k: None for k in state.meta},
        )

    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.pending_state._query_pending_approvals",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_wi_blockers",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_team_requests",
           return_value=[])
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_pending_with_work_item(self, *_m: object) -> None:
        """Work item triggers pending state lookup."""
        state = assemble_context_sync(**_default_state(
            work_item_id="WI-123",
        ))
        self.assertIn(
            "pending_state_injected",
            {k: None for k in state.meta},
        )


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestOnda2Integration(unittest.TestCase):
    """End-to-end tests for Onda 2 features."""

    @patch("app.context_engine.steps.gather.pending_state._query_pending_approvals",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_wi_blockers",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_team_requests",
           return_value=[])
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_full_pipeline_onda2(self, *_m: object) -> None:
        """Full pipeline: resolve → gather → assemble → post."""
        state = assemble_context_sync(**_default_state(
            user_text="como usar tiktoken para contar tokens?",
            session_id="sess-onda2",
            history=[
                {"role": "user", "content": f"msg {i}"}
                for i in range(5)
            ],
        ))

        # All phases should have executed
        self.assertGreater(state.build_ms, 0)
        self.assertIsInstance(state.messages, list)
        self.assertGreater(len(state.messages), 0)

        # Token budget should be populated
        budget = state.meta.get("token_budget", {})
        self.assertIn("tiktoken_available", budget)

        # Tools should be selected
        self.assertIsInstance(state.tools, list)

    @patch("app.rag.ingest_session_turn_facts", return_value=3)
    @patch("app.context_engine.steps.gather.pending_state._query_pending_approvals",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_wi_blockers",
           return_value=[])
    @patch("app.context_engine.steps.gather.pending_state._query_team_requests",
           return_value=[])
    @patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
           return_value="")
    @patch("app.context_engine.steps.gather.system_layers._load_skills",
           return_value=([], []))
    @patch("app.context_engine.steps.gather.system_layers._build_l1",
           return_value=([], {"skipped": True}))
    @patch("app.context_engine.steps.gather.system_layers._build_l4",
           return_value=(None, {"rule_count": 0}))
    def test_schema_tracker_integrated(self, *_m: object) -> None:
        """ToolSelectionStep integrates SchemaTracker."""
        state = assemble_context_sync(**_default_state(
            user_text="read file and execute command",
            session_id="sess-tracker",
            mode="cli",
            connector_alive=True,
            workspace_path="/tmp/test",
        ))

        # Schema tracker meta should be present
        self.assertIn("tools_tracked", state.meta)
        self.assertIn("tools_injected", state.meta)


if __name__ == "__main__":
    unittest.main()
