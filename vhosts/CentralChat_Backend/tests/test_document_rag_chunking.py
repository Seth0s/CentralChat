"""F5 — chunking de texto para RAG de documentos."""
from __future__ import annotations

import unittest

from app.document_rag_chunking import chunk_plaintext


class TestDocumentRagChunking(unittest.TestCase):
    def test_chunk_respects_max_and_overlap(self) -> None:
        text = "x" * 500 + "\n\n" + "y" * 500
        chunks = chunk_plaintext(text, max_chunk_chars=400, overlap=50, max_chunks=10)
        self.assertGreaterEqual(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(len(c), 420)

    def test_empty(self) -> None:
        self.assertEqual(chunk_plaintext("", max_chunk_chars=100, overlap=0, max_chunks=5), [])


if __name__ == "__main__":
    unittest.main()
