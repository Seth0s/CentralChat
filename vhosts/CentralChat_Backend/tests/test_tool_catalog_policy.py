"""ADR17-0 — LLM tool catalog filtering (cloud / client / platform / meta)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.tool_catalog_policy import (
    filter_tool_names_for_llm,
    get_tool_execution_class,
    is_tool_exposed_to_llm,
)
from app.tool_registry import (
    TOOL_NAME_CLIENT_GREP,
    TOOL_NAME_CLIENT_READ_FILE,
    TOOL_NAME_CREATE_APPROVAL_REQUEST,
    TOOL_NAME_GET_HOST_SUMMARY,
    TOOL_NAME_REQUEST_SHELL,
    build_agent_tools_protocol_text,
    list_registered_tool_names_for_llm_prompt,
)


class TestToolCatalogPolicy(unittest.TestCase):
    def test_default_hides_platform_and_meta(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            self.assertFalse(is_tool_exposed_to_llm(TOOL_NAME_GET_HOST_SUMMARY))
            self.assertFalse(is_tool_exposed_to_llm(TOOL_NAME_CREATE_APPROVAL_REQUEST))
            self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_REQUEST_SHELL))
            self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_CLIENT_READ_FILE))
            self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_CLIENT_GREP))
            self.assertEqual(get_tool_execution_class(TOOL_NAME_REQUEST_SHELL), "client")
            self.assertEqual(get_tool_execution_class(TOOL_NAME_CLIENT_READ_FILE), "client")
            self.assertEqual(get_tool_execution_class("web_research"), "cloud")

    def test_legacy_platform_flag_exposes_host_tools(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_GET_HOST_SUMMARY))

    def test_meta_tool_flag(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", True
        ):
            self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_CREATE_APPROVAL_REQUEST))

    def test_llm_prompt_list_excludes_platform_by_default(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            names = list_registered_tool_names_for_llm_prompt()
        self.assertIn(TOOL_NAME_REQUEST_SHELL, names)
        self.assertNotIn(TOOL_NAME_GET_HOST_SUMMARY, names)
        self.assertNotIn(TOOL_NAME_CREATE_APPROVAL_REQUEST, names)

    def test_protocol_text_default_omits_platform(self) -> None:
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            text = build_agent_tools_protocol_text()
        allowed_start = text.index("=== Allowed tools")
        allowed_end = text.index("Tool hints")
        allowed_block = text[allowed_start:allowed_end]
        self.assertIn(TOOL_NAME_REQUEST_SHELL, allowed_block)
        self.assertNotIn(TOOL_NAME_GET_HOST_SUMMARY, allowed_block)
        self.assertNotIn(TOOL_NAME_CREATE_APPROVAL_REQUEST, allowed_block)

    def test_filter_preserves_order(self) -> None:
        raw = ["request_shell", "get_host_summary", "apply_canvas_patch"]
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            out = filter_tool_names_for_llm(raw)
        self.assertEqual(out, ["request_shell", "apply_canvas_patch"])


if __name__ == "__main__":
    unittest.main()
