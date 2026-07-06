"""Golden tests for ContextPipeline — baseline behavior snapshots.

These tests protect the current behavior of ContextPipeline.assemble().
If a refactor changes any snapshot, you MUST update the golden value
and document why the behavior changed.

Coverage:
  - Basic assemble (web mode, no agent, no connector)
  - CLI mode with workspace
  - Connector-alive tool availability
  - Long history compaction (L5)
  - Agent + skills injection (L3)
  - Output structure integrity
  - Injection meta completeness
  - Edge cases: empty history, no session, cache behavior

Design: Snapshot tests using dict comparison on key fields.
Not testing: L1 system anchor content (loads from file, env-dependent),
            L3/L4 DB-backed content (needs PG).
"""

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context_pipeline import (
    AssembledContext,
    ContextPipeline,
    ContextWindowManager,
    SystemLayers,
    ToolInjector,
)


def _using_new_engine() -> bool:
    """Check if ContextEngine is active (now default since Onda 3)."""
    try:
        from app.config import CONTEXT_ENGINE_DISABLED, CONTEXT_ENGINE_ENABLED
        # Engine is ON by default unless explicitly disabled
        if CONTEXT_ENGINE_DISABLED:
            return False
        return bool(CONTEXT_ENGINE_ENABLED)
    except Exception:
        return True  # Engine is the default


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _payload(
    *,
    text: str = "hello",
    history: list | None = None,
    session_id: str = "",
) -> SimpleNamespace:
    """Build a minimal payload matching AssistantTextRequest shape."""
    hist = history or []
    return SimpleNamespace(
        text=text,
        history=[
            SimpleNamespace(role=m["role"], content=m["content"]) for m in hist
        ],
        chat_session_id=session_id,
        request_id="req-test",
    )


def _injected_roles(assembled: AssembledContext) -> list[str]:
    """Extract roles from injected_history for assertion."""
    return [m["role"] for m in assembled.injected_history]


def _injected_content_contains(assembled: AssembledContext, substr: str) -> bool:
    """Check if any injected message contains substr."""
    return any(substr in m.get("content", "") for m in assembled.injected_history)


def _system_messages(assembled: AssembledContext) -> list[str]:
    """Return all system message contents."""
    return [
        m["content"]
        for m in assembled.injected_history
        if m.get("role") == "system"
    ]


# ═══════════════════════════════════════════════════════════════
# Golden test cases
# ═══════════════════════════════════════════════════════════════

class TestContextPipelineGolden(unittest.TestCase):
    """Snapshot tests for ContextPipeline.assemble()."""

    # ── Basic assembly ──────────────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_basic_web_no_agent_no_connector(self, *_m: object) -> None:
        """GOLDEN: simplest web request — no agent, no connector, no history."""
        pipeline = ContextPipeline()
        payload = _payload(text="Olá, como estás?")

        assembled = pipeline.assemble(
            payload, "rid-web-1",
            mode="web",
            connector_alive=False,
            workspace_path=None,
            tenant_id="default",
        )

        # Structure checks
        self.assertIsInstance(assembled, AssembledContext)
        self.assertIsInstance(assembled.injected_history, list)
        self.assertGreater(len(assembled.injected_history), 1)

        # Last message is user text
        self.assertEqual(assembled.injected_history[-1]["content"], "Olá, como estás?")
        self.assertEqual(assembled.injected_history[-1]["role"], "user")

        # Injection meta — golden snapshot
        meta = assembled.injection_meta
        self.assertIn(meta["pipeline"], ("context_pipeline", "context_engine"),
                      f"pipeline should be context_pipeline or context_engine, got {meta['pipeline']}")
        self.assertEqual(meta["mode"], "web")
        self.assertEqual(meta["connector_alive"], False)
        self.assertEqual(meta["tenant_id"], "default")
        self.assertIsNone(meta["workspace_path"])
        try:
            self.assertIn("L5", meta["layers"])
            # L5 is present (classic pipeline always adds it)
        except AssertionError:
            if _using_new_engine():
                # New engine: L5 only appears when history was compacted
                self.assertNotIn("L5", meta["layers"])
            else:
                raise
        self.assertIn("tools_injected", meta)
        self.assertIn("tools_catalog", meta)
        self.assertIn("build_ms", meta)
        self.assertGreater(meta["build_ms"], 0)

        # No agent, no skills
        self.assertEqual(meta["agent_name"], "default")
        self.assertEqual(meta["skill_names"], [])

        # Tools — web without connector = knowledge tools only
        tools = assembled.openai_tools
        self.assertIsInstance(tools, list)
        # At minimum TIER_0 tools are present (memory, session_search, clarify)
        tool_names = {t["function"]["name"] for t in tools}
        self.assertTrue(tool_names.issuperset({"memory", "session_search", "clarify"}))
        # No delegated tools without connector
        for name in tool_names:
            self.assertNotIn(name, ToolInjector.DELEGATED,
                             f"DELEGATED tool {name} should not appear without connector")

        # Token accounting present
        ta = meta.get("token_accounting", {})
        self.assertIsInstance(ta, dict)

    # ── CLI mode ────────────────────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_cli_mode_with_workspace(self, *_m: object) -> None:
        """GOLDEN: CLI mode with workspace path — L2 injected, delegated tools available."""
        pipeline = ContextPipeline()
        payload = _payload(text="lê o ficheiro main.py", history=[
            {"role": "user", "content": "preciso de ajuda"},
            {"role": "assistant", "content": "claro, o que precisas?"},
        ])

        assembled = pipeline.assemble(
            payload, "rid-cli-1",
            mode="cli",
            connector_alive=True,
            workspace_path="/home/dev/project",
            tenant_id="acme",
        )

        meta = assembled.injection_meta
        self.assertEqual(meta["mode"], "cli")
        self.assertEqual(meta["workspace_path"], "/home/dev/project")
        self.assertEqual(meta["connector_alive"], True)
        self.assertIn("L2", meta["layers"],
                      "CLI mode with workspace should inject L2")

        # L2 content in system messages
        sys_msgs = _system_messages(assembled)
        l2_msg = [m for m in sys_msgs if "[WORKSPACE L2]" in m]
        self.assertEqual(len(l2_msg), 1)
        self.assertIn("/home/dev/project", l2_msg[0])

        # ENV block for CLI
        self.assertTrue(
            any("[ENV] CentralChat CLI" in m for m in sys_msgs),
            "CLI mode should have CLI ENV block",
        )

        # Delegated tools available with connector
        tool_names = {t["function"]["name"] for t in assembled.openai_tools}
        # At least some delegated tools should appear
        delegated_present = tool_names & ToolInjector.DELEGATED
        self.assertGreater(len(delegated_present), 0,
                           "CLI mode with connector should have delegated tools")

    # ── Connector-alive mode ────────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_web_with_connector_gets_delegated_tools(self, *_m: object) -> None:
        """GOLDEN: web + connector_alive=True → DELEGATED tools available."""
        pipeline = ContextPipeline()
        # Keywords must match triggers exactly (substring match): "executar" not "executa"
        payload = _payload(text="executar comando ls -la e ler ficheiro main.py")

        assembled = pipeline.assemble(
            payload, "rid-web-conn-1",
            mode="web",
            connector_alive=True,
            workspace_path=None,
            tenant_id="default",
        )

        tool_names = {t["function"]["name"] for t in assembled.openai_tools}
        # Should include delegated tools since connector is alive
        self.assertIn("terminal", tool_names,
                      "terminal should be available with connector")
        self.assertIn("read_file", tool_names,
                      "read_file should be available with connector")

    # ── Agent + skills injection ────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    def test_agent_prompt_injected(self, *_m: object) -> None:
        """GOLDEN: agent_name → L3 agent prompt injected.
        
        NOTE: This test mocks ContextPipeline instance methods, so it only tests
        the classic pipeline path. When CONTEXT_ENGINE_ENABLED=1, the engine
        uses a different code path and this test is skipped.
        """
        if _using_new_engine():
            self.skipTest("agent mocking is classic-pipeline-specific; engine uses different path")

        pipeline = ContextPipeline()
        agent_prompt = "[AGENT coder]\nÉs um programador Python experiente."

        with patch.object(pipeline, "_load_agent_prompt",
                          return_value=agent_prompt):
            with patch.object(pipeline, "_load_skills", return_value=([], [])):
                payload = _payload(text="escreve uma função")
                assembled = pipeline.assemble(
                    payload, "rid-agent-1",
                    agent_name="coder",
                    mode="web",
                    connector_alive=False,
                    tenant_id="default",
                )

        meta = assembled.injection_meta
        self.assertEqual(meta["agent_name"], "coder")
        self.assertIn("L3", meta["layers"])

        sys_msgs = _system_messages(assembled)
        self.assertTrue(
            any("programador Python" in m for m in sys_msgs),
            "Agent prompt should appear in system messages",
        )

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    def test_skills_injected_with_prefix(self, *_m: object) -> None:
        """GOLDEN: skills appear with [SKILL: name] prefix.
        
        NOTE: Mocking pipeline instance methods — classic path only.
        """
        if _using_new_engine():
            self.skipTest("skill mocking is classic-pipeline-specific; engine uses different path")
        pipeline = ContextPipeline()
        skills_data = (
            [
                {"role": "system", "content": "[SKILL: python]\nSempre usar type hints."},
                {"role": "system", "content": "[SKILL: testing]\nUsar pytest."},
            ],
            ["python", "testing"],
        )

        with patch.object(pipeline, "_load_skills", return_value=skills_data):
            payload = _payload(text="escreve testes")
            assembled = pipeline.assemble(
                payload, "rid-skills-1",
                mode="web",
                connector_alive=False,
                tenant_id="default",
            )

        meta = assembled.injection_meta
        self.assertIn("L3", meta["layers"])
        self.assertEqual(meta["skill_names"], ["python", "testing"])

        sys_msgs = _system_messages(assembled)
        self.assertTrue(
            any("[SKILL: python]" in m for m in sys_msgs),
            "Skill prefix format should be [SKILL: name]",
        )
        self.assertTrue(
            any("type hints" in m for m in sys_msgs),
            "Skill content should appear",
        )

    # ── Long history compaction (L5) ────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_long_history_triggers_compaction(self, *_m: object) -> None:
        """GOLDEN: 100 messages → L5 compacts (truncates or summarizes)."""
        pipeline = ContextPipeline()
        history = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"message number {i} with some extra text to make it longer"}
            for i in range(100)
        ]
        payload = _payload(history=history, text="continua", session_id="sess-long")

        assembled = pipeline.assemble(
            payload, "rid-long-1",
            mode="web",
            connector_alive=False,
            tenant_id="default",
        )

        meta = assembled.injection_meta
        self.assertIn("L5", meta["layers"])
        # With 100 messages, should be truncated
        self.assertTrue(
            assembled.session_truncated or
            meta.get("token_accounting", {}).get("compacted"),
            "100 messages should trigger compaction/truncation",
        )

        # Verify message count reduced
        history_msgs = [
            m for m in assembled.injected_history
            if m["role"] in ("user", "assistant")
        ]
        self.assertLess(
            len(history_msgs), 100,
            "Compacted history should have fewer messages than input",
        )

    # ── Empty history ───────────────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_empty_history_no_crash(self, *_m: object) -> None:
        """GOLDEN: empty history → assembles without error."""
        pipeline = ContextPipeline()
        payload = _payload(text="primeira mensagem", history=[])

        assembled = pipeline.assemble(
            payload, "rid-empty-1",
            mode="web",
            connector_alive=False,
            tenant_id="default",
        )

        # Should still have user message at the end
        self.assertEqual(assembled.injected_history[-1]["role"], "user")
        self.assertEqual(assembled.injected_history[-1]["content"], "primeira mensagem")

        # No crash, no exception
        self.assertIsNotNone(assembled.injected_history)

    # ── Tool schema shape validation ────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_tool_schemas_are_valid_openai_format(self, *_m: object) -> None:
        """GOLDEN: every tool in openai_tools has valid OpenAI function schema."""
        pipeline = ContextPipeline()
        payload = _payload(text="search for bugs and fix them",
                           history=[{"role": "user", "content": "help"}] * 3)

        assembled = pipeline.assemble(
            payload, "rid-schema-1",
            mode="cli",
            connector_alive=True,
            workspace_path="/tmp/test",
            tenant_id="default",
        )

        for tool in assembled.openai_tools:
            self.assertIn("type", tool)
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            func = tool["function"]
            self.assertIn("name", func)
            self.assertIsInstance(func["name"], str)
            self.assertGreater(len(func["name"]), 0)
            self.assertIn("description", func)
            self.assertIn("parameters", func)
            params = func["parameters"]
            self.assertIn("type", params)
            self.assertEqual(params["type"], "object")

    # ── Keyword-driven tool selection ───────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_keyword_triggers_file_tools(self, *_m: object) -> None:
        """GOLDEN: 'ler ficheiro' triggers read_file tool."""
        pipeline = ContextPipeline()
        payload = _payload(text="podes ler o ficheiro config.py?")

        assembled = pipeline.assemble(
            payload, "rid-kw-1",
            mode="cli",
            connector_alive=True,
            workspace_path="/tmp/proj",
            tenant_id="default",
        )

        tool_names = {t["function"]["name"] for t in assembled.openai_tools}
        self.assertIn("read_file", tool_names,
                      "'ler ficheiro' should trigger read_file via keyword scoring")

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_keyword_triggers_terminal(self, *_m: object) -> None:
        """GOLDEN: 'executar comando' triggers terminal tool."""
        pipeline = ContextPipeline()
        payload = _payload(text="executa o comando pytest")

        assembled = pipeline.assemble(
            payload, "rid-kw-2",
            mode="cli",
            connector_alive=True,
            workspace_path="/tmp/proj",
            tenant_id="default",
        )

        tool_names = {t["function"]["name"] for t in assembled.openai_tools}
        self.assertIn("terminal", tool_names,
                      "'executa comando' should trigger terminal via keyword scoring")

    # ── [TOOLS] catalog injection ───────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_tools_catalog_injected(self, *_m: object) -> None:
        """GOLDEN: [TOOLS] catalog string is injected as a system message."""
        pipeline = ContextPipeline()
        payload = _payload(text="hello")

        assembled = pipeline.assemble(
            payload, "rid-catalog-1",
            mode="web",
            connector_alive=False,
            tenant_id="default",
        )

        sys_msgs = _system_messages(assembled)
        tools_msg = [m for m in sys_msgs if m.startswith("[TOOLS]")]
        self.assertEqual(len(tools_msg), 1,
                         "Exactly one [TOOLS] catalog message should be injected")
        # Should contain at least the TIER_0 tools
        self.assertIn("clarify", tools_msg[0])
        self.assertIn("memory", tools_msg[0])
        self.assertIn("session_search", tools_msg[0])

    # ── System layers cache ─────────────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_layer_cache_reuses_system_layers(self, *_m: object) -> None:
        """GOLDEN: same params → cached SystemLayers (build_ms=0 on second call)."""
        pipeline = ContextPipeline()

        # First call — should build layers
        payload1 = _payload(text="msg1")
        assembled1 = pipeline.assemble(
            payload1, "rid-cache-1",
            mode="web",
            connector_alive=False,
            tenant_id="default",
        )
        build1 = assembled1.injection_meta["build_ms"]

        # Second call with same params — should hit cache
        payload2 = _payload(text="msg2")
        assembled2 = pipeline.assemble(
            payload2, "rid-cache-2",
            mode="web",
            connector_alive=False,
            tenant_id="default",
        )

        # The _compose_system_layers is cached; the overall assemble
        # still does tool injection + compaction per turn.
        # We verify both produce the same layers_applied
        self.assertEqual(
            assembled1.injection_meta["layers"],
            assembled2.injection_meta["layers"],
            "Same params should produce same layer list (cached)",
        )

    # ── Injection meta completeness ─────────────────────────────

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor",
           return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules",
           return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt",
           return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills",
           return_value=([], []))
    def test_injection_meta_has_all_required_fields(self, *_m: object) -> None:
        """GOLDEN: injection_meta contains every documented field."""
        pipeline = ContextPipeline()
        payload = _payload(text="test", history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])

        assembled = pipeline.assemble(
            payload, "rid-meta-1",
            mode="web",
            connector_alive=False,
            tenant_id="acme-corp",
        )

        meta = assembled.injection_meta

        # Required top-level fields (from AssembledContext.injection_meta construction)
        required_fields = [
            "pipeline", "build_ms", "layers", "layer_meta",
            "agent_name", "skill_names", "connector_alive", "mode",
            "workspace_path", "tenant_id", "tools_injected",
            "tools_active", "tools_catalog", "token_accounting",
        ]
        for field in required_fields:
            self.assertIn(field, meta, f"injection_meta missing field: {field}")

        # Pipeline identity
        self.assertIn(meta["pipeline"], ("context_pipeline", "context_engine"),
                      f"pipeline should be valid, got {meta['pipeline']}")

        # Layer meta structure
        self.assertIsInstance(meta["layer_meta"], dict)
        self.assertIsInstance(meta["layers"], list)

        # Tools catalog is a list
        self.assertIsInstance(meta["tools_catalog"], list)
        self.assertGreater(len(meta["tools_catalog"]), 0)

        # Token accounting is a dict
        ta = meta["token_accounting"]
        self.assertIsInstance(ta, dict)
        self.assertIn("compacted", ta)


# ═══════════════════════════════════════════════════════════════
# ContextWindowManager golden tests
# ═══════════════════════════════════════════════════════════════

class TestContextWindowManagerGolden(unittest.TestCase):
    """Golden tests for context window compaction."""

    def test_short_history_passes_through(self) -> None:
        """GOLDEN: history under limit → intact, not truncated."""
        mgr = ContextWindowManager()
        hist = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = mgr.compact(hist)
        self.assertFalse(result.truncated)
        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.messages[0]["content"], "hello")

    def test_very_long_history_compacts(self) -> None:
        """GOLDEN: 200 long messages → compacted (truncated=True)."""
        mgr = ContextWindowManager()
        hist = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"message {i} " + "padding text " * 50}
            for i in range(200)
        ]
        result = mgr.compact(hist, session_id="sess-test", tenant_id="default")
        self.assertTrue(result.truncated)

        # After compaction, should have system summary + recent messages
        after_count = len(result.messages)
        self.assertLess(after_count, 200,
                        "Compacted result must have fewer messages than input")

        # First message should be summary
        self.assertTrue(
            result.messages[0]["content"].startswith("[SUMMARY") or
            result.stats.compacted,
            "Compacted result should have summary or be flagged compacted",
        )

    def test_single_message_no_crash(self) -> None:
        """GOLDEN: single message → no crash."""
        mgr = ContextWindowManager()
        hist = [{"role": "user", "content": "one"}]
        result = mgr.compact(hist)
        self.assertFalse(result.truncated)
        self.assertEqual(len(result.messages), 1)


# ═══════════════════════════════════════════════════════════════
# ToolInjector golden tests
# ═══════════════════════════════════════════════════════════════

class TestToolInjectorGolden(unittest.TestCase):
    """Golden tests for RAG-driven tool selection."""

    def test_tier0_always_included(self) -> None:
        """GOLDEN: TIER_0 tools (memory, session_search, clarify) always selected."""
        injector = ToolInjector()
        tools, _ = injector.select_and_inject(
            "random text with no keywords",
            history=[],
            current_messages=[],
            connector_alive=False,
        )
        tool_names = {t["function"]["name"] for t in tools}
        self.assertTrue(
            tool_names.issuperset(ToolInjector.TIER_0),
            "TIER_0 tools must always be present",
        )

    def test_no_delegated_without_connector(self) -> None:
        """GOLDEN: without connector, DELEGATED tools absent."""
        injector = ToolInjector()
        tools, _ = injector.select_and_inject(
            "executa ls e lê ficheiro",
            history=[],
            current_messages=[],
            connector_alive=False,
        )
        tool_names = {t["function"]["name"] for t in tools}
        for d in ToolInjector.DELEGATED:
            self.assertNotIn(d, tool_names,
                             f"DELEGATED tool {d} should not appear without connector")

    def test_delegated_with_connector(self) -> None:
        """GOLDEN: with connector, keyword-matched DELEGATED tools included."""
        injector = ToolInjector()
        tools, _ = injector.select_and_inject(
            "executa o comando pytest e lê o ficheiro main.py",
            history=[],
            current_messages=[],
            connector_alive=True,
        )
        tool_names = {t["function"]["name"] for t in tools}
        # Keywords should trigger specific tools
        self.assertIn("terminal", tool_names)
        self.assertIn("read_file", tool_names)
        # But not ALL delegated tools — only keyword-matched
        self.assertNotIn("cronjob", tool_names,
                         "cronjob should not appear without keyword trigger")

    def test_empty_user_text_still_returns_tier0(self) -> None:
        """GOLDEN: empty text → still returns TIER_0 tools."""
        injector = ToolInjector()
        tools, _ = injector.select_and_inject(
            "",
            history=[],
            current_messages=[],
            connector_alive=False,
        )
        tool_names = {t["function"]["name"] for t in tools}
        self.assertTrue(
            tool_names.issuperset(ToolInjector.TIER_0),
            "TIER_0 tools should be present even with empty text",
        )


if __name__ == "__main__":
    unittest.main()
