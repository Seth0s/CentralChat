"""ADR17-6 — connector_status on GET /config."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.server import app


class TestConnectorStatusConfig(unittest.TestCase):
    @patch("app.connector_status.build_connector_status_public_snapshot")
    def test_config_includes_connector_status(self, mock_snap: unittest.mock.MagicMock) -> None:
        mock_snap.return_value = {
            "client_execution_enabled": True,
            "online": False,
            "connector_count": 0,
            "connectors": [],
        }
        client = TestClient(app)
        r = client.get("/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("connector_status", body)
        self.assertFalse(body["connector_status"]["online"])

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
    def test_snapshot_disabled_when_legacy(self) -> None:
        from app.connector_status import build_connector_status_public_snapshot

        snap = build_connector_status_public_snapshot(tenant_id="default")
        self.assertFalse(snap["client_execution_enabled"])
