"""F5 — mensagem system de excertos."""
from __future__ import annotations

import unittest

from app.prompt_injection import build_document_rag_system_message


class TestDocumentRagPrompt(unittest.TestCase):
    def test_build_includes_chunks(self) -> None:
        msg = build_document_rag_system_message(
            doc_id="demo",
            doc_title="Demo",
            chunks=[(0, "alpha"), (2, "beta")],
            max_chars=4000,
        )
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertEqual(msg["role"], "system")
        self.assertIn("demo", msg["content"])
        self.assertIn("[chunk 0]", msg["content"])
        self.assertIn("alpha", msg["content"])


if __name__ == "__main__":
    unittest.main()
