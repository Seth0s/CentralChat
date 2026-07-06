"""AST + HERMES-ADAPT tests.

Tests:
- AST parser (parse Python files)
- AST store (query, upsert)
- ask_project tool (execute + dispatch)
- Environment gates (label → tool scoping)
- TIER_0 includes ask_project
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.context_engine import assemble_context_sync
from app.context_engine.registry import STEP_REGISTRY, list_steps, Phase


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _write_temp_py(code: str) -> str:
    """Write code to a temp .py file, return path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
    tmp.write(code)
    tmp.close()
    return tmp.name


# ═══════════════════════════════════════════════════════════════
# AST Parser tests
# ═══════════════════════════════════════════════════════════════

class TestAstParser(unittest.TestCase):
    """AST parser extracts code structure from Python files."""

    def test_parse_simple_function(self) -> None:
        """Extract function with docstring and signature."""
        from app.ast_parser import parse_file

        code = '''"""Module doc."""

def hello(name: str) -> str:
    """Say hello."""
    return f"Hello {name}"
'''
        path = _write_temp_py(code)
        try:
            result = parse_file(path)
            self.assertGreater(len(result.nodes), 0)
            self.assertEqual(result.nodes[0].node_type, "module")
            # Find the function node
            funcs = [n for n in result.nodes if n.node_type == "function"]
            self.assertEqual(len(funcs), 1)
            self.assertEqual(funcs[0].name, "hello")
            self.assertEqual(funcs[0].docstring, "Say hello.")
            self.assertIn("name", funcs[0].signature or "")
        finally:
            os.unlink(path)

    def test_parse_class_with_methods(self) -> None:
        """Extract class and its methods."""
        from app.ast_parser import parse_file

        code = '''
class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
'''
        path = _write_temp_py(code)
        try:
            result = parse_file(path)
            classes = [n for n in result.nodes if n.node_type == "class"]
            self.assertEqual(len(classes), 1)
            self.assertEqual(classes[0].name, "Calculator")
            self.assertEqual(classes[0].docstring, "A simple calculator.")

            methods = [n for n in result.nodes if n.node_type == "method"]
            self.assertEqual(len(methods), 2)
            self.assertEqual(methods[0].name, "add")
            self.assertEqual(methods[1].name, "subtract")
        finally:
            os.unlink(path)

    def test_parse_imports(self) -> None:
        """Extract import statements."""
        from app.ast_parser import parse_file

        code = '''
import os
from pathlib import Path
from app.models import User, Session
'''
        path = _write_temp_py(code)
        try:
            result = parse_file(path)
            imports = [n for n in result.nodes if n.node_type == "import"]
            self.assertGreaterEqual(len(imports), 3)
            names = {n.name for n in imports}
            self.assertIn("os", names)
        finally:
            os.unlink(path)

    def test_parse_syntax_error(self) -> None:
        """Syntax error returns empty nodes with error."""
        from app.ast_parser import parse_file

        path = _write_temp_py("def broken( {{ ")
        try:
            result = parse_file(path)
            self.assertEqual(len(result.nodes), 0)
            self.assertGreater(len(result.errors), 0)
        finally:
            os.unlink(path)

    def test_source_hash(self) -> None:
        """File gets a SHA-256 source hash."""
        from app.ast_parser import parse_file

        path = _write_temp_py("# test file\nx = 1\n")
        try:
            result = parse_file(path)
            self.assertIsNotNone(result.source_hash)
            self.assertEqual(len(result.source_hash), 64)
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════
# ask_project tool tests
# ═══════════════════════════════════════════════════════════════

class TestAskProjectTool(unittest.TestCase):
    """ask_project tool execution and registration."""

    def test_tool_registered_in_specs(self) -> None:
        """ask_project is in DEFAULT_TOOL_SPECS."""
        from app.default_tools import DEFAULT_TOOL_SPECS, TOOL_NAME_ASK_PROJECT
        self.assertIn(TOOL_NAME_ASK_PROJECT, DEFAULT_TOOL_SPECS)

    def test_tool_has_dispatch(self) -> None:
        """ask_project has a dispatch function."""
        from app.default_tools import _DEFAULT_TOOL_DISPATCH, TOOL_NAME_ASK_PROJECT
        self.assertIn(TOOL_NAME_ASK_PROJECT, _DEFAULT_TOOL_DISPATCH)

    def test_execute_without_pg(self) -> None:
        """execute_ask_project returns empty results without PG."""
        from app.ast_tool import execute_ask_project

        result = execute_ask_project("where is auth?", tenant_id="default")
        self.assertIn("count", result)
        self.assertEqual(result["count"], 0)

    def test_tier0_includes_ask_project(self) -> None:
        """ask_project is in TIER_0 for both ToolInjector and ToolSelectionStep."""
        from app.context_pipeline import ToolInjector
        from app.context_engine.steps.gather.tool_selection import InjectorConstants

        self.assertIn("ask_project", ToolInjector.TIER_0)
        self.assertIn("ask_project", InjectorConstants.TIER_0)

    def test_trigger_keywords(self) -> None:
        """ask_project has trigger keywords registered."""
        from app.context_pipeline import _TRIGGER_MAP

        self.assertIn("ask_project", _TRIGGER_MAP)
        self.assertGreater(len(_TRIGGER_MAP["ask_project"]), 0)


# ═══════════════════════════════════════════════════════════════
# Environment gates tests
# ═══════════════════════════════════════════════════════════════

class TestEnvironmentGates(unittest.TestCase):
    """H-6: WI label → tool scoping."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [
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
        for p in cls._patchers:
            p.start()

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    def test_step_registered(self) -> None:
        """EnvironmentGateStep is registered at priority 13."""
        self.assertIn("gather.environment_gates", STEP_REGISTRY)
        step = STEP_REGISTRY["gather.environment_gates"]
        self.assertEqual(step.phase, Phase.GATHER)
        self.assertEqual(step.priority, 13)

    def test_backend_label_scoping(self) -> None:
        """'backend' label maps to backend tool set."""
        from app.context_engine.steps.gather.environment_gates import _LABEL_TOOL_SCOPE

        scope = _LABEL_TOOL_SCOPE.get("backend", set())
        self.assertIn("terminal", scope)
        self.assertIn("write_file", scope)
        self.assertIn("delegate_task", scope)

    def test_frontend_label_scoping(self) -> None:
        """'frontend' label maps to frontend tool set."""
        from app.context_engine.steps.gather.environment_gates import _LABEL_TOOL_SCOPE

        scope = _LABEL_TOOL_SCOPE.get("frontend", set())
        self.assertIn("web_search", scope)
        self.assertIn("vision_analyze", scope)
        self.assertNotIn("terminal", scope)

    def test_unknown_label_no_restriction(self) -> None:
        """Unknown labels don't restrict tools."""
        from app.context_engine.steps.gather.environment_gates import _LABEL_TOOL_SCOPE

        self.assertNotIn("unknown-label", _LABEL_TOOL_SCOPE)


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestAstIntegration(unittest.TestCase):
    """End-to-end AST pipeline tests."""

    def test_step_count_19(self) -> None:
        """Total step count is 19."""
        self.assertEqual(len(STEP_REGISTRY), 19)

    def test_environment_gates_phase_order(self) -> None:
        """Environment gates run after file_lease, before retrieval."""
        gather_steps = list_steps(Phase.GATHER)
        names = [s.name for s in gather_steps]
        flease_idx = names.index("gather.file_lease")
        env_idx = names.index("gather.environment_gates")
        ret_idx = names.index("gather.retrieval")
        self.assertLess(flease_idx, env_idx,
                        "environment_gates should run after file_lease")
        self.assertLess(env_idx, ret_idx,
                        "environment_gates should run before retrieval")

    def test_ask_project_importable(self) -> None:
        """All AST modules are importable."""
        import app.ast_parser
        import app.ast_store
        import app.ast_routes
        import app.ast_tool

        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
