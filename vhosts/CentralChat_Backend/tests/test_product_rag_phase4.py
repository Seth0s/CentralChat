"""Phase 4 — Central product pack + product RAG + D7 tool resolution."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.central_product_pack import (
    CENTRAL_CAPABILITIES_URI,
    CENTRAL_CORE_URI,
    build_central_product_pack_messages,
    get_central_product_public_snapshot,
)
from app.product_rag import (
    build_product_rag_system_message,
    resolve_tool_names_product_rag,
    tool_names_from_product_hits,
)
from app.product_rag_store_pgvector import ProductRagHit
from app.system_prompt_loader import build_system_prompt_injection_messages
from app.tool_registry import TOOL_NAME_REQUEST_SHELL, build_agent_tools_protocol_text


class TestCentralProductPack(unittest.TestCase):
    @patch("app.config.CENTRAL_PRODUCT_PACK_ENABLED", True)
    def test_pack_messages_include_uris(self) -> None:
        msgs, audit = build_central_product_pack_messages()
        self.assertGreaterEqual(len(msgs), 2)
        joined = "\n".join(m["content"] for m in msgs)
        self.assertIn(CENTRAL_CORE_URI, joined)
        self.assertIn(CENTRAL_CAPABILITIES_URI, joined)
        self.assertTrue(audit.get("central_core_applied"))

    @patch("app.config.CENTRAL_PRODUCT_PACK_ENABLED", True)
    def test_public_snapshot_uris(self) -> None:
        snap = get_central_product_public_snapshot()
        self.assertEqual(snap["uris"]["core"], CENTRAL_CORE_URI)
        self.assertIn(CENTRAL_CORE_URI, snap["versions"])

    @patch("app.config.CENTRAL_PRODUCT_PACK_ENABLED", True)
    @patch("app.config.CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED", True)
    @patch("app.config.CENTRAL_FOCUS_MODE", False)
    def test_loader_includes_central_after_l6(self) -> None:
        msgs, audit = build_system_prompt_injection_messages()
        self.assertTrue(audit.get("central_core_applied"))
        contents = [m.get("content") or "" for m in msgs]
        l6_idx = next((i for i, c in enumerate(contents) if "[POLICY_ANCHOR]" in c), -1)
        core_idx = next((i for i, c in enumerate(contents) if "SYSTEM_CENTRAL_CORE" in c), -1)
        self.assertGreaterEqual(l6_idx, 0)
        self.assertGreater(core_idx, l6_idx)


class TestProductRagPrompt(unittest.TestCase):
    def test_build_context_message(self) -> None:
        hits = [
            ProductRagHit(
                source_key="tool:request_shell",
                title="request_shell",
                chunk_index=0,
                content="Run governed shell.",
                score=0.9,
                kind="tool",
            )
        ]
        msg = build_product_rag_system_message(hits, max_chars=4000)
        assert msg is not None
        self.assertIn("CONTEXT_RETRIEVED", msg["content"])
        self.assertIn("request_shell", msg["content"])

    def test_tool_names_from_hits(self) -> None:
        hits = [
            ProductRagHit("tool:request_shell", "t", 0, "x", 0.5, "tool"),
            ProductRagHit("doc:central://core@v1", "c", 0, "y", 0.4, "doc"),
        ]
        names = tool_names_from_product_hits(hits)
        self.assertEqual(names, ["request_shell"])


class TestToolsOnlyViaRetrieval(unittest.TestCase):
    @patch("app.config.CENTRAL_PRODUCT_RAG_ENABLED", True)
    @patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", True)
    @patch("app.product_rag.search_product_context")
    def test_no_full_catalog_on_empty_hits(self, mock_search: MagicMock) -> None:
        mock_search.return_value = ([], {"hit_count": 0})
        from app.tool_registry import list_registered_tool_names

        names, info = resolve_tool_names_product_rag(user_text="disk space")
        self.assertLess(len(names), len(list_registered_tool_names()))
        self.assertIn(TOOL_NAME_REQUEST_SHELL, names)
        self.assertEqual(info.get("mode"), "product_rag_retrieval_only")

    @patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", True)
    @patch("app.config.AGENT_TOOLS_RAG_ENABLED", False)
    @patch("app.config.CENTRAL_PRODUCT_RAG_ENABLED", False)
    def test_product_rag_off_tools_only_returns_always_include(self) -> None:
        from app.product_rag import resolve_tool_names_product_rag

        names, info = resolve_tool_names_product_rag(user_text="x")
        self.assertIn(TOOL_NAME_REQUEST_SHELL, names)
        self.assertEqual(info.get("mode"), "always_include_only")

    @patch("app.config.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", True)
    @patch("app.config.AGENT_TOOLS_RAG_ENABLED", True)
    @patch("app.config.CENTRAL_PRODUCT_RAG_ENABLED", False)
    @patch("app.agent_tools_rag.count_agent_tools_rows", return_value=0)
    @patch("app.agent_tools_rag.embed_agent_tools_text", return_value=([0.0] * 8, "m"))
    def test_legacy_empty_store_tools_only(self, *_mocks: MagicMock) -> None:
        from app.agent_tools_rag import resolve_registered_tool_names_for_prompt

        names, info = resolve_registered_tool_names_for_prompt(user_text="x")
        self.assertIn(TOOL_NAME_REQUEST_SHELL, names)
        self.assertEqual(info.get("mode"), "always_include_only")


class TestProtocolSubset(unittest.TestCase):
    def test_protocol_subset_smaller_than_full(self) -> None:
        full = build_agent_tools_protocol_text()
        sub = build_agent_tools_protocol_text([TOOL_NAME_REQUEST_SHELL])
        self.assertLess(len(sub), len(full))
        self.assertIn("request_shell", sub)


if __name__ == "__main__":
    unittest.main()
