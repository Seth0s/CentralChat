"""F4 — selecção RAG do catálogo de tools."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_tools_store_pgvector import AgentToolHit
from app.agent_tools_rag import resolve_registered_tool_names_for_prompt
from app.tool_registry import (
    TOOL_NAME_REQUEST_SHELL,
    build_agent_tools_protocol_text,
    list_registered_tool_names_for_llm_prompt,
)


class TestAgentToolsRag(unittest.TestCase):
    def test_rag_disabled_returns_full_catalog(self) -> None:
        with patch("app.config.AGENT_TOOLS_RAG_ENABLED", False), patch(
            "app.config.CENTRAL_PRODUCT_RAG_ENABLED", False
        ), patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", False):
            names, info = resolve_registered_tool_names_for_prompt(user_text="disco cheio")
        self.assertEqual(names, list_registered_tool_names_for_llm_prompt())
        self.assertFalse(info["enabled"])
        self.assertEqual(info["mode"], "full_catalog")

    @patch("app.agent_tools_rag.search_agent_tools")
    @patch("app.agent_tools_rag.count_agent_tools_rows")
    @patch("app.agent_tools_rag.embed_agent_tools_text")
    def test_rag_merges_similarity_and_always_include(
        self,
        mock_embed: unittest.mock.MagicMock,
        mock_count: unittest.mock.MagicMock,
        mock_search: unittest.mock.MagicMock,
    ) -> None:
        mock_embed.return_value = ([0.01] * 384, "local_hash_384_v1")
        mock_count.return_value = 20
        mock_search.return_value = [AgentToolHit(name="manage_workspace_artifact", score=0.95)]
        with patch("app.config.AGENT_TOOLS_RAG_ENABLED", True), patch(
            "app.config.CENTRAL_PRODUCT_RAG_ENABLED", False
        ), patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", False), patch(
            "app.config.CENTRAL_FOCUS_MODE", False
        ):
            names, info = resolve_registered_tool_names_for_prompt(user_text="espaco em disco")
        self.assertEqual(info["mode"], "rag")
        self.assertIn("manage_workspace_artifact", names)
        if TOOL_NAME_REQUEST_SHELL in list_registered_tool_names_for_llm_prompt():
            self.assertIn(TOOL_NAME_REQUEST_SHELL, names)

    @patch("app.agent_tools_rag.search_agent_tools")
    @patch("app.agent_tools_rag.count_agent_tools_rows")
    @patch("app.agent_tools_rag.embed_agent_tools_text")
    def test_empty_store_degrades_to_full(
        self,
        mock_embed: unittest.mock.MagicMock,
        mock_count: unittest.mock.MagicMock,
        mock_search: unittest.mock.MagicMock,
    ) -> None:
        mock_embed.return_value = ([0.01] * 384, "local_hash_384_v1")
        mock_count.return_value = 0
        with patch("app.config.AGENT_TOOLS_RAG_ENABLED", True), patch(
            "app.config.CENTRAL_PRODUCT_RAG_ENABLED", False
        ), patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", False), patch(
            "app.config.CENTRAL_FOCUS_MODE", False
        ):
            names, info = resolve_registered_tool_names_for_prompt(user_text="x")
        self.assertEqual(names, list_registered_tool_names_for_llm_prompt())
        self.assertEqual(info["mode"], "degraded_empty_store")

    def test_central_focus_suppresses_rag_even_when_env_enabled(self) -> None:
        with patch("app.config.AGENT_TOOLS_RAG_ENABLED", True), patch(
            "app.config.CENTRAL_PRODUCT_RAG_ENABLED", False
        ), patch("app.config.CENTRAL_FOCUS_MODE", True):
            names, info = resolve_registered_tool_names_for_prompt(user_text="qualquer")
        self.assertEqual(names, list_registered_tool_names_for_llm_prompt())
        self.assertFalse(info["enabled"])
        self.assertEqual(info["mode"], "full_catalog")
        self.assertEqual(info.get("suppressed_by"), "central_focus_mode")


class TestBuildAgentToolsProtocolSubset(unittest.TestCase):
    def test_subset_limits_hints(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            sub = ["get_host_summary", "list_processes"]
            text = build_agent_tools_protocol_text(sub)
        self.assertIn("get_host_summary", text)
        self.assertIn("list_processes", text)
        self.assertNotIn("grep_workspace", text)


if __name__ == "__main__":
    unittest.main()
