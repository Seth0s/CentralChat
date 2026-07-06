"""P5 — compliance ops, async audit export, SIEM monitor tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.admin_routes as admin_routes
from app.shared.siem_outbox import siem_outbox_summary


class SiemOutboxSummaryTest(unittest.TestCase):
    @patch("app.shared.siem_outbox.memory_db_enabled", return_value=False)
    def test_summary_disabled(self, *_m: object) -> None:
        out = siem_outbox_summary()
        self.assertEqual(out["status"], "disabled")


class AdminP5RoutesTest(unittest.TestCase):
    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "build_deploy_status", return_value={"tenant_id": "acme"})
    def test_admin_deploy_status_shape(self, *_m: object) -> None:
        out = admin_routes.admin_deploy_status()
        self.assertEqual(out["tenant_id"], "acme")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "siem_outbox_summary", return_value={"status": "ok", "dead": 0})
    def test_admin_siem_outbox_shape(self, *_m: object) -> None:
        out = admin_routes.admin_siem_outbox_status()
        self.assertTrue(out["ok"])

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "memory_db_enabled", return_value=True)
    @patch.object(admin_routes, "create_audit_export_job")
    def test_admin_audit_export_create(self, mock_create: MagicMock, *_m: object) -> None:
        mock_create.return_value = {"id": "job-1", "status": "pending"}
        body = admin_routes.AuditExportCreateBody(format="csv", since="7d")
        out = admin_routes.admin_audit_exports_create(body)
        self.assertTrue(out["ok"])
        mock_create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
