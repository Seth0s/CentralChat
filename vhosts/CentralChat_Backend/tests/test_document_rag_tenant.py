"""Phase 5 — document RAG tenant-scoped helpers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.document_rag import search_document_context
from app.document_rag_store_pgvector import DocumentRagHit


class TestDocumentRagModule(unittest.TestCase):
    @patch("app.document_rag.count_document_rag_chunks", return_value=3)
    @patch("app.document_rag.search_document_rag_chunks")
    @patch("app.document_rag.get_embedding_service")
    @patch("app.document_rag.cfg.DOCUMENT_RAG_SERVER_ENABLED", True)
    @patch("app.document_rag.resolve_pg_tenant_id", return_value="tenant-a")
    def test_search_uses_tenant_and_embedding_model(
        self,
        _tid: MagicMock,
        mock_emb: MagicMock,
        mock_search: MagicMock,
        _count: MagicMock,
    ) -> None:
        mock_emb.return_value.embed_tools.return_value = ([0.2] * 4, "emb_v2")
        mock_search.return_value = [
            DocumentRagHit(chunk_index=0, content="chunk", title="T", score=0.8),
        ]
        hits, meta = search_document_context(doc_id="manual", query="deploy", tenant_id="tenant-a")
        self.assertEqual(len(hits), 1)
        self.assertEqual(meta["tenant_id"], "tenant-a")
        self.assertEqual(meta["embedding_model_id"], "emb_v2")
        mock_search.assert_called_once()
        call_kw = mock_search.call_args.kwargs
        self.assertEqual(call_kw["tenant_id"], "tenant-a")
        self.assertEqual(call_kw["embedding_model_id"], "emb_v2")

    @patch("app.document_rag_store_pgvector.memory_db_enabled", return_value=False)
    def test_count_returns_zero_when_db_off(self, _mock: MagicMock) -> None:
        from app.document_rag_store_pgvector import count_document_rag_chunks

        self.assertEqual(count_document_rag_chunks(tenant_id="t1"), 0)


if __name__ == "__main__":
    unittest.main()
