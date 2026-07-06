"""ADR17-7 — client_tools RAG namespace."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.product_rag import tool_names_from_product_hits
from app.product_rag_store_pgvector import ProductRagHit
from app.tool_registry import (
    TOOL_NAME_CLIENT_GREP,
    TOOL_NAME_CLIENT_READ_FILE,
    TOOL_NAME_REQUEST_SHELL,
    iter_client_tool_rag_source_rows,
)


class TestClientToolsRag(unittest.TestCase):
    def test_iter_client_rows_includes_new_tools(self) -> None:
        names = {row[0] for row in iter_client_tool_rag_source_rows()}
        self.assertIn(TOOL_NAME_REQUEST_SHELL, names)
        self.assertIn(TOOL_NAME_CLIENT_READ_FILE, names)
        self.assertIn(TOOL_NAME_CLIENT_GREP, names)

    def test_product_hits_parse_client_tool_kind(self) -> None:
        hits = [
            ProductRagHit(
                source_key=f"client_tool:{TOOL_NAME_CLIENT_READ_FILE}",
                title=TOOL_NAME_CLIENT_READ_FILE,
                chunk_index=0,
                content="hint",
                score=0.9,
                kind="client_tool",
            )
        ]
        with patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False), patch(
            "app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", False
        ):
            names = tool_names_from_product_hits(hits)
        self.assertEqual(names, [TOOL_NAME_CLIENT_READ_FILE])
