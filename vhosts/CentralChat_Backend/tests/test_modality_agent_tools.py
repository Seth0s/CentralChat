"""ADR-016 phase 6 — modality agent tools registry and dispatch."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import jsonschema

from app.modality_agent_tools import (
    MODALITY_TOOL_SPECS,
    TOOL_NAME_DRAFT_SOCIAL_POST,
    TOOL_NAME_GENERATE_POST_IMAGE,
    TOOL_NAME_WEB_RESEARCH,
    run_draft_social_post,
    run_generate_post_image,
    run_web_research,
)


class TestModalityAgentToolsSchemas(unittest.TestCase):
    def test_web_research_requires_query(self) -> None:
        schema = MODALITY_TOOL_SPECS[TOOL_NAME_WEB_RESEARCH]["arguments_schema"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({}, schema)
        jsonschema.validate({"query": "kubernetes security"}, schema)

    def test_web_research_rejects_bad_tier(self) -> None:
        schema = MODALITY_TOOL_SPECS[TOOL_NAME_WEB_RESEARCH]["arguments_schema"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"query": "x", "tier": "ultra"}, schema)

    def test_draft_social_requires_platform_and_topic(self) -> None:
        schema = MODALITY_TOOL_SPECS[TOOL_NAME_DRAFT_SOCIAL_POST]["arguments_schema"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"platform": "x"}, schema)
        jsonschema.validate({"platform": "x", "topic": "evento domingo"}, schema)

    def test_generate_image_requires_prompt(self) -> None:
        schema = MODALITY_TOOL_SPECS[TOOL_NAME_GENERATE_POST_IMAGE]["arguments_schema"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"aspect": "1:1"}, schema)


class TestModalityToolsRegistryFlag(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        from app.tool_registry import is_registered_tool

        self.assertFalse(is_registered_tool(TOOL_NAME_WEB_RESEARCH))
        self.assertFalse(is_registered_tool(TOOL_NAME_DRAFT_SOCIAL_POST))
        self.assertFalse(is_registered_tool(TOOL_NAME_GENERATE_POST_IMAGE))

    @patch("app.config.CENTRAL_MODALITY_TOOLS_ENABLED", True)
    @patch("app.config.MODALITY_AGENT_TOOLS_PATH", "")
    @patch("app.config.PRIMARY_AGENT_TOOLS_PATH", "")
    def test_enabled_merges_tools(self) -> None:
        from app.tool_registry import _build_active_tool_specs

        specs = _build_active_tool_specs()
        self.assertIn(TOOL_NAME_WEB_RESEARCH, specs)
        wr_schema = specs[TOOL_NAME_WEB_RESEARCH]["arguments_schema"]
        jsonschema.validate({"query": "teste"}, wr_schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"platform": "x"}, specs[TOOL_NAME_DRAFT_SOCIAL_POST]["arguments_schema"])


class TestModalityToolsDispatch(unittest.TestCase):
    @patch("app.modality_agent_tools.call_llm")
    @patch("app.modality_agent_tools.resolve_modality_call_params")
    def test_web_research_dispatch(self, mock_resolve, mock_llm) -> None:
        mock_resolve.return_value = ("cloud_gemini", "perplexity/sonar-pro")
        mock_llm.return_value = "## Resumo\nFacto.\n\n## Fontes\nhttps://example.com/a"
        out = run_web_research("req-1", query="IA na igreja", tier="default")
        self.assertTrue(out["ok"])
        self.assertIn("example.com", out["sources"][0])
        mock_llm.assert_called_once()
        self.assertEqual(mock_llm.call_args.kwargs.get("allowlist_mode"), "modality")

    @patch("app.modality_agent_tools.call_llm")
    @patch("app.modality_agent_tools.resolve_modality_call_params")
    def test_draft_social_dispatch(self, mock_resolve, mock_llm) -> None:
        mock_resolve.return_value = ("cloud_gemini", "x-ai/grok-4.1-fast")
        mock_llm.return_value = "Post rascunho #central"
        out = run_draft_social_post("req-2", platform="x", topic="culto", max_chars=280)
        self.assertTrue(out["ok"])
        self.assertEqual(out["draft"], "Post rascunho #central")

    @patch("app.config.CENTRAL_IMAGE_GENERATE_HITL", True)
    def test_image_hitl_skips_llm(self) -> None:
        with patch("app.modality_agent_tools.call_llm") as mock_llm:
            with patch(
                "app.modality_agent_tools.resolve_modality_call_params",
                return_value=("cloud_gemini", "google/gemini-2.5-flash-image"),
            ):
                out = run_generate_post_image("req-3", prompt="altar com luz")
        self.assertEqual(out["status"], "hitl_pending")
        mock_llm.assert_not_called()


class TestAgentToolsProtocolNoSonarCatalog(unittest.TestCase):
    def test_protocol_hints_no_openrouter_sonar_ids(self) -> None:
        from app.tool_registry import build_agent_tools_protocol_text

        text = build_agent_tools_protocol_text().lower()
        self.assertNotIn("perplexity/sonar-pro", text)
        self.assertNotIn("perplexity/sonar-deep-research", text)
