"""T17 — Testes para Multi-Agent Tree.

Cobre:
  - T17.1: Modelos (AgentTreeIn, AgentNodeIn, AgentTreeOut, AgentNodeOut)
  - T17.2: CRUD endpoints (trees + nodes)
  - T17.3: AgentTreeRunner (execução de árvore)
  - T17.4: Spawn paralelo de nós filhos
  - T17.5: Propagação de contexto (inherit_mode)
  - T17.6: Agregação de resultados
  - T17.7: Cancelamento propagado
  - T17.8: HITL por nó
  - T17.9: SSE events
  - T17.10: Integração ContextEngine + Runner + Tools
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _set_env():
    os.environ.setdefault("CENTRAL_DEFAULT_TOOLS_ENABLED", "1")
    os.environ.setdefault("CENTRAL_ROOT", os.path.join(os.path.dirname(__file__), ".."))


# ═══ T17.1: MODELS ═══


class TestModels:
    def test_tree_create_input(self):
        from app.agent_tree import AgentTreeIn

        tree = AgentTreeIn(name="Test Tree", description="A test")
        assert tree.name == "Test Tree"
        assert tree.description == "A test"

    def test_node_create_input(self):
        from app.agent_tree import AgentNodeIn

        node = AgentNodeIn(
            agent_name="coder",
            position=0,
            label="Code Review",
            config={"model": "gpt-4o"},
            inherit_mode="summary",
        )
        assert node.agent_name == "coder"
        assert node.inherit_mode == "summary"
        assert node.config["model"] == "gpt-4o"

    def test_node_inherit_mode_validation(self):
        from pydantic import ValidationError
        from app.agent_tree import AgentNodeIn

        with pytest.raises(ValidationError):
            AgentNodeIn(inherit_mode="invalid")

    def test_tree_execute_request(self):
        from app.agent_tree import TreeExecuteRequest

        req = TreeExecuteRequest(user_text="Hello world")
        assert req.user_text == "Hello world"


# ═══ T17.3–T17.9: RUNNER ═══


class TestAgentTreeRunner:
    def test_runner_init(self):
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner(max_parallel=4)
        assert runner is not None

    def test_build_tree_flat(self):
        """T17.3 — Constrói árvore a partir de lista plana."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        nodes = [
            {"id": "n1", "parent_id": None, "agent_name": "root", "position": 0, "label": "Root", "config": {}, "inherit_mode": "full"},
            {"id": "n2", "parent_id": "n1", "agent_name": "child1", "position": 1, "label": "Child 1", "config": {}, "inherit_mode": "full"},
            {"id": "n3", "parent_id": "n1", "agent_name": "child2", "position": 2, "label": "Child 2", "config": {}, "inherit_mode": "full"},
        ]
        tree = runner._build_tree(nodes)
        assert tree["id"] == "n1"
        assert len(tree["children"]) == 2
        assert tree["children"][0]["id"] == "n2"
        assert tree["children"][1]["id"] == "n3"

    def test_build_tree_single_node(self):
        """T17.3 — Árvore com um único nó."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        nodes = [
            {"id": "n1", "parent_id": None, "agent_name": "solo", "position": 0, "label": "Solo", "config": {}, "inherit_mode": "full"},
        ]
        tree = runner._build_tree(nodes)
        assert tree["id"] == "n1"
        assert tree["children"] == []

    def test_inherited_context_none(self):
        """T17.5 — inherit_mode=none: apenas user_text."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        ctx = runner._build_inherited_context("user msg", "parent summary", "none")
        assert ctx == "user msg"

    def test_inherited_context_summary(self):
        """T17.5 — inherit_mode=summary: apenas inherited_summary."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        ctx = runner._build_inherited_context("user msg", "parent summary", "summary")
        assert ctx == "parent summary"

    def test_inherited_context_full(self):
        """T17.5 — inherit_mode=full: inherited + user text."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        ctx = runner._build_inherited_context("user msg", "parent summary", "full")
        assert "parent summary" in ctx
        assert "user msg" in ctx

    def test_aggregate_concat(self):
        """T17.6 — Agregação concat."""
        from app.agent_tree import AgentTreeRunner, NodeResult

        runner = AgentTreeRunner()
        results = [
            NodeResult(node_id="c1", agent_name="coder", label="", reply="Code is clean"),
            NodeResult(node_id="c2", agent_name="reviewer", label="", reply="LGTM"),
        ]
        node = {"config": {"aggregate_mode": "concat"}}
        reply = runner._aggregate_results(node, results, "review this")
        assert "coder" in reply
        assert "reviewer" in reply
        assert "Code is clean" in reply
        assert "LGTM" in reply

    def test_aggregate_error(self):
        """T17.6 — Agregação com erro num child."""
        from app.agent_tree import AgentTreeRunner, NodeResult

        runner = AgentTreeRunner()
        results = [
            NodeResult(node_id="c1", agent_name="bad", label="", error="connection failed"),
            NodeResult(node_id="c2", agent_name="good", label="", reply="All good"),
        ]
        node = {"config": {"aggregate_mode": "concat"}}
        reply = runner._aggregate_results(node, results, "test")
        assert "ERROR" in reply
        assert "All good" in reply

    def test_cancel_sets_event(self):
        """T17.7 — Cancelamento propaga evento."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        # Register a cancel event manually
        import threading
        ev = threading.Event()
        runner._cancel_events["test-tree"] = ev
        ok = runner.cancel_tree("test-tree")
        assert ok is True
        assert ev.is_set()

    def test_cancel_unknown_tree(self):
        """T17.7 — Cancelar tree inexistente retorna False."""
        from app.agent_tree import AgentTreeRunner

        runner = AgentTreeRunner()
        ok = runner.cancel_tree("nonexistent")
        assert ok is False

    def test_sse_line_format(self):
        """T17.9 — SSE line format."""
        from app.agent_tree import sse_line

        line = sse_line("node_start", {"node_id": "n1", "agent_name": "test"})
        assert line.startswith("event: node_start\n")
        assert "node_id" in line
        assert "agent_name" in line
        assert line.endswith("\n\n")

    def test_node_result_dataclass(self):
        """T17.9 — NodeResult dataclass."""
        from app.agent_tree import NodeResult

        nr = NodeResult(node_id="n1", agent_name="coder", label="Review", reply="OK", elapsed_ms=42.0)
        assert nr.node_id == "n1"
        assert nr.reply == "OK"
        assert nr.elapsed_ms == 42.0
        assert nr.error is None


# ═══ T17.10: INTEGRATION ═══


class TestIntegration:
    def test_runner_leaf_without_db(self):
        """T17.10 — Runner leaf executa sem DB (usa ContextEngine)."""
        from app.agent_tree import AgentTreeRunner
        import threading

        runner = AgentTreeRunner(max_parallel=2)
        node = {
            "id": "leaf1",
            "agent_name": "default",
            "label": "Test Leaf",
            "config": {},
            "inherit_mode": "full",
            "children": [],
        }
        cancel = threading.Event()
        reply = runner._call_agent_llm(node, "what is 2+2?", "", cancel)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_runner_leaf_with_inherited(self):
        """T17.10 — Runner leaf com inherited context."""
        from app.agent_tree import AgentTreeRunner
        import threading

        runner = AgentTreeRunner(max_parallel=2)
        node = {
            "id": "leaf2",
            "agent_name": "default",
            "label": "Inherited Leaf",
            "config": {},
            "inherit_mode": "full",
            "children": [],
        }
        cancel = threading.Event()
        reply = runner._call_agent_llm(node, "summarize", "Previous: code review found 3 bugs", cancel)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_router_exists(self):
        """T17.10 — Router registado."""
        from app.agent_tree import router_agent_tree

        assert router_agent_tree is not None
        assert router_agent_tree.prefix == "/agent-trees"
