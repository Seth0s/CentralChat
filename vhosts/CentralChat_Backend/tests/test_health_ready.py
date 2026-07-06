"""Onda A — /health/ready unit tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestHealthReady(unittest.TestCase):
    @patch("app.shared.pg_tenant.memory_db_enabled", return_value=False)
    def test_ready_when_db_disabled(self, *_m: object) -> None:
        from app.server import app

        r = TestClient(app).get("/health/ready")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["checks"]["postgres"]["status"], "disabled")

    @patch("app.shared.pg_tenant.connect_pg")
    @patch("app.shared.pg_tenant.memory_db_enabled", return_value=True)
    def test_ready_when_pg_ok(self, _mem: object, mock_connect: object) -> None:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        mock_connect.return_value.__enter__.return_value = conn
        from app.server import app

        r = TestClient(app).get("/health/ready")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["checks"]["postgres"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
