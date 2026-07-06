"""P4 — agents, rules, policy bundle governance tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.admin_routes as admin_routes
import app.memory_service as ms


class TeamCatalogP4Test(unittest.TestCase):
    @patch.object(ms, "memory_db_enabled", return_value=True)
    @patch.object(ms, "ensure_team_catalog_schema")
    @patch.object(ms, "connect_pg")
    @patch("app.audit_service.append_audit_event")
    def test_reject_team_rule_sets_flag(self, mock_audit: MagicMock, mock_pg: MagicMock, *_m: object) -> None:
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("rule-1", "Never patch prod", "manual")
        mock_pg.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
        out = ms.reject_team_rule("rule-1", reason="Too vague", tenant_id="acme", rejected_by="lead-1")
        self.assertIsNotNone(out)
        self.assertTrue(out["rejected"])
        mock_audit.assert_called()

    @patch.object(ms, "memory_db_enabled", return_value=False)
    def test_reject_team_rule_requires_db(self, *_m: object) -> None:
        self.assertIsNone(ms.reject_team_rule("rule-1", reason="x"))


class PolicyAdminRoutesTest(unittest.TestCase):
    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "get_active_policy_summary", return_value={"tenant_id": "acme", "active": None})
    def test_admin_policies_active_shape(self, *_m: object) -> None:
        out = admin_routes.admin_policies_active()
        self.assertEqual(out["tenant_id"], "acme")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "memory_db_enabled", return_value=True)
    @patch.object(admin_routes, "rollback_policy_bundle", return_value={"ok": True, "version": 2})
    def test_admin_policies_rollback_shape(self, mock_rollback: MagicMock, *_m: object) -> None:
        body = admin_routes.PolicyRollbackBody(version=2)
        out = admin_routes.admin_policies_rollback(body)
        self.assertTrue(out["ok"])
        mock_rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
