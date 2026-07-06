"""Phase 5 — session namespace RAG."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.product_rag_store_pgvector import ProductRagHit
from app.prompt_injection import build_session_facts_extract_prompt
from app.session_rag import build_session_rag_system_message, ingest_session_facts
from app.session_rag_worker import extract_session_facts_heuristic, ingest_session_turn_facts


class TestSessionFactsHeuristic(unittest.TestCase):
    def test_extracts_user_and_assistant(self) -> None:
        facts = extract_session_facts_heuristic(
            user_text="Qual o estado do deploy?",
            assistant_text="O deploy está verde.",
        )
        self.assertGreaterEqual(len(facts), 1)
        self.assertTrue(any("deploy" in f.lower() for f in facts))


class TestSessionRagPrompt(unittest.TestCase):
    def test_build_message_includes_session_id(self) -> None:
        hits = [
            ProductRagHit(
                source_key="session:abc:turn:x:0",
                title="session:abc",
                chunk_index=0,
                content="User prefers dark mode",
                score=0.9,
                kind="session",
            )
        ]
        msg = build_session_rag_system_message(hits, chat_session_id="abcd1234", max_chars=2000)
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("abcd1234", msg["content"])
        self.assertIn("dark mode", msg["content"])

    def test_extract_prompt_has_roles(self) -> None:
        p = build_session_facts_extract_prompt(user_text="hi", assistant_text="bye")
        self.assertIn("USER:", p)
        self.assertIn("ASSISTANT:", p)


class TestSessionRagIngest(unittest.TestCase):
    @patch("app.session_rag_worker.ingest_session_facts", return_value=2)
    @patch("app.config.CENTRAL_SESSION_RAG_ENABLED", True)
    @patch("app.config.CENTRAL_FOCUS_MODE", False)
    def test_worker_calls_ingest(self, mock_ingest: MagicMock) -> None:
        n = ingest_session_turn_facts(
            chat_session_id="12345678-abcd",
            user_text="pergunta",
            assistant_text="resposta longa",
        )
        self.assertEqual(n, 2)
        mock_ingest.assert_called_once()

    @patch("app.session_rag.upsert_product_chunk")
    @patch("app.session_rag.get_embedding_service")
    @patch("app.config.CENTRAL_SESSION_RAG_ENABLED", True)
    @patch("app.config.CENTRAL_FOCUS_MODE", False)
    def test_ingest_writes_chunks(self, mock_emb: MagicMock, mock_upsert: MagicMock) -> None:
        mock_emb.return_value.embed_tools.return_value = ([0.1] * 8, "test_emb_v1")
        written = ingest_session_facts(
            chat_session_id="12345678-abcd",
            facts=["fact one"],
        )
        self.assertEqual(written, 1)
        mock_upsert.assert_called_once()
        kw = mock_upsert.call_args.kwargs
        self.assertEqual(kw["kind"], "session")
        self.assertEqual(kw["metadata"]["chat_session_id"], "12345678-abcd")


if __name__ == "__main__":
    unittest.main()
