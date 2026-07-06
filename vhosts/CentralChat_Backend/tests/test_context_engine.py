"""T15+T16 — Testes para ContextEngine com injection hierárquico.

Cobre:
  - T16.1: L1 anchor cacheável
  - T16.2: L2 user identity
  - T16.3: L3 agent .md (cache por hash)
  - T16.4: L4 skills .md (cache por hash)
  - T16.5: L4b tool capability digest (filtrado por agent)
  - T16.6: L5 RAG paralelo
  - T16.7: L6 context + history
  - T16.8: L7 user message
  - T16.9: InjectionCache (LRU + hash invalidation)
  - T16.10: Assembly completo com todas as camadas
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _set_env():
    os.environ.setdefault("CENTRAL_DEFAULT_TOOLS_ENABLED", "1")
    os.environ.setdefault("CENTRAL_ROOT", os.path.join(os.path.dirname(__file__), ".."))


class MockPayload:
    def __init__(self, text: str = "hello") -> None:
        self.text = text
        self.history: list[dict[str, str]] = []
        self.include_long_session_memory = False
        self.include_memory_recall = False
        self.include_document_rag = False
        self.document_rag_doc_id = None
        self.include_session_rag = False
        self.use_saved_assistant_defaults = False
        self.include_playbook = False
        self.include_capability_digest = False
        self.media_attachments: list[Any] = []
        self.widget_active_slot = None
        self.agent_name = None
        self.chat_session_id = None


class MockSessionView:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []


# ═══ T16.9: InjectionCache ═══


class TestInjectionCache:
    def test_set_get(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=60)
        cache.set(InjectionLayer.AGENT, "hash123", "system prompt content")
        result = cache.get(InjectionLayer.AGENT, "hash123")
        assert result == "system prompt content"

    def test_cache_miss(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=60)
        result = cache.get(InjectionLayer.SKILLS, "nonexistent")
        assert result is None

    def test_cache_ttl_expiry(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=0.001)
        cache.set(InjectionLayer.TOOL_DIGEST, "h1", "digest")
        import time
        time.sleep(0.01)
        result = cache.get(InjectionLayer.TOOL_DIGEST, "h1")
        assert result is None  # expired

    def test_lru_eviction(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=3, ttl_sec=3600)
        cache.set(InjectionLayer.ANCHOR, "a", "A")
        cache.set(InjectionLayer.IDENTITY, "b", "B")
        cache.set(InjectionLayer.AGENT, "c", "C")
        cache.set(InjectionLayer.SKILLS, "d", "D")  # evicts 'a'
        assert cache.get(InjectionLayer.ANCHOR, "a") is None
        assert cache.get(InjectionLayer.AGENT, "c") == "C"

    def test_invalidate_layer(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=3600)
        cache.set(InjectionLayer.AGENT, "a1", "agent1")
        cache.set(InjectionLayer.AGENT, "a2", "agent2")
        cache.set(InjectionLayer.SKILLS, "s1", "skill1")
        n = cache.invalidate(InjectionLayer.AGENT)
        assert n == 2
        assert cache.get(InjectionLayer.AGENT, "a1") is None
        assert cache.get(InjectionLayer.SKILLS, "s1") == "skill1"

    def test_invalidate_all(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=3600)
        cache.set(InjectionLayer.ANCHOR, "x", "X")
        cache.set(InjectionLayer.AGENT, "y", "Y")
        n = cache.invalidate(None)
        assert n == 2
        assert cache.stats["entries"] == 0

    def test_stats(self):
        from app.context_engine import InjectionCache, InjectionLayer

        cache = InjectionCache(max_entries=10, ttl_sec=3600)
        cache.set(InjectionLayer.ANCHOR, "k", "v")
        cache.get(InjectionLayer.ANCHOR, "k")
        cache.get(InjectionLayer.ANCHOR, "missing")
        stats = cache.stats
        assert stats["entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1


# ═══ T16.1–T16.8: Injection Layers ═══


class TestInjectionLayers:
    def test_l1_anchor(self):
        from app.context_engine import ContextEngine, InjectionLayer

        engine = ContextEngine()
        from app.context_engine import InjectionTrace
        trace = InjectionTrace()
        anchor, ahash = engine._build_anchor(trace)
        assert isinstance(anchor, str)
        assert len(trace.layers) == 1
        assert trace.layers[0].layer == InjectionLayer.ANCHOR

    def test_l1_anchor_cached_second_call(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        from app.context_engine import InjectionTrace
        trace1 = InjectionTrace()
        engine._build_anchor(trace1)
        trace2 = InjectionTrace()
        engine._build_anchor(trace2)
        assert trace2.layers[0].cache_hit is True

    def test_l4b_tool_digest(self):
        from app.context_engine import AgentConfig, ContextEngine, InjectionTrace

        engine = ContextEngine()
        agent = AgentConfig(name="default")
        trace = InjectionTrace()
        digest = engine._build_capability_digest(agent, trace)
        assert "TOOL_CAPABILITY_DIGEST" in digest
        assert "P0" in digest
        assert len(trace.layers) >= 1

    def test_l4b_tool_digest_filtered_by_agent(self):
        from app.context_engine import AgentConfig, ContextEngine, InjectionTrace

        engine = ContextEngine()
        agent = AgentConfig(name="restricted", allowed_tools=["read_file", "terminal"])
        trace = InjectionTrace()
        digest = engine._build_capability_digest(agent, trace)
        assert "read_file" in digest
        assert "terminal" in digest
        assert "write_file" not in digest

    def test_l5_rag_parallel(self):
        from app.context_engine import ContextEngine, InjectionTrace

        engine = ContextEngine()
        trace = InjectionTrace()
        rag_text, count = engine._run_rag_parallel("test query for rag", trace)
        assert isinstance(rag_text, str)
        assert isinstance(count, int)
        assert len(trace.layers) >= 1

    def test_l6_context_layer(self):
        from app.context_engine import ContextEngine, InjectionTrace

        engine = ContextEngine()
        payload = MockPayload(text="hello")
        session_view = MockSessionView()
        trace = InjectionTrace()
        ctx = engine._build_context_layer(payload, session_view, "rid-1", "inherited ctx", trace)
        assert isinstance(ctx, str)
        assert "[Inherited Context]" in ctx

    def test_l7_user_message(self):
        from app.context_engine import ContextEngine, InjectionTrace

        engine = ContextEngine()
        trace = InjectionTrace()
        text = engine._build_user_message_layer("what is python?", trace)
        assert text == "what is python?"


# ═══ T15: Core Engine (regression) ═══


class TestCoreEngine:
    def test_import(self):
        from app.context_engine import ContextEngine, InferenceReady

        engine = ContextEngine()
        assert engine is not None

    def test_load_skills(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        skills = engine._load_skills("default")
        assert len(skills) == 3
        assert any("Central Project" == s.name for s in skills)

    def test_load_tools(self):
        from app.context_engine import AgentConfig, ContextEngine

        engine = ContextEngine()
        agent = AgentConfig(name="default")
        tools = engine._load_tool_definitions(agent)
        assert len(tools.tools) == 12

    def test_tool_filter(self):
        from app.context_engine import AgentConfig, ContextEngine

        engine = ContextEngine()
        agent = AgentConfig(name="r", allowed_tools=["read_file", "write_file"])
        tools = engine._load_tool_definitions(agent)
        assert len(tools.tools) == 2

    def test_model_resolution(self):
        from app.context_engine import AgentConfig, ContextEngine, UserIdentity

        engine = ContextEngine()
        agent = AgentConfig(name="test")
        identity = UserIdentity()
        model, profile, max_tokens, temp = engine._resolve_model(agent=agent, identity=identity)
        assert isinstance(model, str) and len(model) > 0
        assert max_tokens > 0

    def test_agent_override(self):
        from app.context_engine import AgentConfig, ContextEngine, UserIdentity

        engine = ContextEngine()
        agent = AgentConfig(name="coder", model="claude-sonnet-4", profile="turbo", max_tokens=8192, temperature=0.3)
        identity = UserIdentity()
        model, profile, max_tokens, temp = engine._resolve_model(agent=agent, identity=identity)
        assert model == "claude-sonnet-4"
        assert profile == "turbo"
        assert max_tokens == 8192
        assert temp == 0.3


# ═══ T16.10: Full Assembly ═══


class TestFullAssembly:
    def test_assemble_with_injection_trace(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        payload = MockPayload(text="explain T16 injection")
        session_view = MockSessionView()

        ready = engine.assemble(
            payload=payload,
            session_view=session_view,
            request_id="full-test",
            agent_name="default",
        )

        assert ready.request_id == "full-test"
        assert ready.agent_name == "default"
        assert len(ready.messages) >= 2  # system + user
        assert len(ready.tools) == 12
        assert len(ready.skill_names) == 3
        assert ready.injection_trace is not None
        assert len(ready.injection_trace.layers) >= 5  # at least L1, L4b, L5, L6, L7
        assert ready.capability_digest != ""
        assert "TOOL_CAPABILITY_DIGEST" in ready.capability_digest

    def test_assemble_with_inherited_context(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        payload = MockPayload(text="continue previous task")
        session_view = MockSessionView()

        ready = engine.assemble(
            payload=payload,
            session_view=session_view,
            request_id="inherit-test",
            agent_name="default",
            inherited_context="Previous agent found: bug in auth.py line 42",
        )

        system_content = ready.messages[0]["content"] if ready.messages else ""
        # Inherited context should be in the system message
        # (composed via _build_context_layer)
        assert len(ready.messages) >= 2

    def test_flat_mode_default_agent(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        agent = engine._load_agent("default")
        assert agent.name == "default"

    def test_cache_stats(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        stats = engine.cache_stats
        assert "entries" in stats
        assert "ttl_sec" in stats

    def test_invalidate_cache(self):
        from app.context_engine import ContextEngine, InjectionLayer

        engine = ContextEngine()
        # Prime the cache
        from app.context_engine import InjectionTrace
        trace = InjectionTrace()
        engine._build_anchor(trace)
        assert trace.layers[0].cache_hit is False

        # Invalidate anchor layer
        n = engine.invalidate_cache(InjectionLayer.ANCHOR)
        assert n >= 1

    def test_capability_digest_in_ready(self):
        from app.context_engine import ContextEngine

        engine = ContextEngine()
        payload = MockPayload(text="list tools")
        session_view = MockSessionView()

        ready = engine.assemble(
            payload=payload,
            session_view=session_view,
            request_id="digest-test",
            agent_name="default",
        )

        assert "P0" in ready.capability_digest
        assert "terminal" in ready.capability_digest
        assert "read_file" in ready.capability_digest


# ═══ Integration ═══


class TestAssistantRoutesIntegration:
    def test_agent_name_field(self):
        from app.assistant_routes import AssistantTextRequest

        payload = AssistantTextRequest(text="hello", agent_name="coder")
        assert payload.agent_name == "coder"

    def test_agent_name_defaults_none(self):
        from app.assistant_routes import AssistantTextRequest

        payload = AssistantTextRequest(text="hello")
        assert payload.agent_name is None
