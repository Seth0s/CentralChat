"""OC-14 — GET /ui/memory-context e build_ui_memory_context (sem PII)."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient


class TestMemoryContext(unittest.TestCase):
    def setUp(self) -> None:
        # Import app after env patches if needed
        from app.server import app

        self.client = TestClient(app)

    def test_memory_context_schema(self) -> None:
        r = self.client.get("/ui/memory-context")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get("schema_version"), 2)
        self.assertIn("memory_db", data)
        self.assertIn("playbook", data)
        self.assertIn("defaults_from_preferences", data)
        self.assertIn("session", data)
        mem = data["memory_db"]
        self.assertIn("enabled", mem)
        self.assertIn("db_configured", mem)
        self.assertNotIn("passage", str(data).lower())
        # Não deve haver chaves com texto longo de recall
        self.assertNotIn("recall_text", data)

    def test_memory_context_no_raw_content(self) -> None:
        from app.memory_context import build_ui_memory_context

        ctx = build_ui_memory_context()
        self.assertIsInstance(ctx["memory_db"]["top_k"], int)
        self.assertIn("note_pt", ctx)


if __name__ == "__main__":
    unittest.main()
