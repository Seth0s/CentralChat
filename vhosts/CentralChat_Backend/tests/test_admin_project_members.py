"""Admin project membership routes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.admin_routes as admin_routes


class AdminProjectMembersTest(unittest.TestCase):
    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "list_org_health")
    def test_admin_org_health_shape(self, mock_health: MagicMock, *_m: object) -> None:
        mock_health.return_value = {
            "tenant_id": "acme",
            "groups_without_projects": [],
            "projects_without_direct_lead": [],
            "counts": {
                "groups": 0,
                "projects": 0,
                "groups_without_projects": 0,
                "projects_without_direct_lead": 0,
            },
            "org_enabled": True,
        }
        out = admin_routes.admin_org_health()
        self.assertTrue(out["org_enabled"])
        self.assertEqual(out["counts"]["projects_without_direct_lead"], 0)

    def test_project_member_put_audits_created_membership(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        user_id = "00000000-0000-4000-8000-000000000011"
        membership = {
            "id": "m1",
            "tenant_id": "acme",
            "user_id": user_id,
            "scope_type": "project",
            "scope_id": project_id,
            "role": "developer",
        }
        with patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme"):
            with patch.object(admin_routes, "require_can_manage_project"):
                with patch.object(admin_routes, "list_project_members", return_value=[]):
                    with patch.object(admin_routes, "upsert_membership", return_value=membership):
                        with patch.object(admin_routes, "_audit_project_membership") as mock_audit:
                            out = admin_routes.admin_project_members_put(
                                project_id,
                                user_id,
                                admin_routes.ProjectMemberBody(role="developer"),
                            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["membership"]["role"], "developer")
        mock_audit.assert_called_once()
        self.assertEqual(mock_audit.call_args.args[0], "project_member.added")
        self.assertEqual(mock_audit.call_args.kwargs["metadata"]["to_role"], "developer")

    def test_project_member_put_audits_role_change(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        user_id = "00000000-0000-4000-8000-000000000011"
        previous = {"user_id": user_id, "role": "developer"}
        membership = {
            "id": "m1",
            "tenant_id": "acme",
            "user_id": user_id,
            "scope_type": "project",
            "scope_id": project_id,
            "role": "lead",
        }
        with patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme"):
            with patch.object(admin_routes, "require_can_manage_project"):
                with patch.object(admin_routes, "list_project_members", return_value=[previous]):
                    with patch.object(admin_routes, "upsert_membership", return_value=membership):
                        with patch.object(admin_routes, "_audit_project_membership") as mock_audit:
                            admin_routes.admin_project_members_put(
                                project_id,
                                user_id,
                                admin_routes.ProjectMemberBody(role="lead"),
                            )

        self.assertEqual(mock_audit.call_args.args[0], "project_member.role_changed")
        self.assertEqual(mock_audit.call_args.kwargs["metadata"]["from_role"], "developer")
        self.assertEqual(mock_audit.call_args.kwargs["metadata"]["to_role"], "lead")

    def test_project_member_delete_audits_removed_membership(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        user_id = "00000000-0000-4000-8000-000000000011"
        previous = {"user_id": user_id, "role": "developer"}
        with patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme"):
            with patch.object(admin_routes, "require_can_manage_project"):
                with patch.object(admin_routes, "list_project_members", return_value=[previous]):
                    with patch.object(admin_routes, "delete_membership", return_value=True):
                        with patch.object(admin_routes, "_audit_project_membership") as mock_audit:
                            out = admin_routes.admin_project_members_delete(project_id, user_id)

        self.assertTrue(out["ok"])
        mock_audit.assert_called_once()
        self.assertEqual(mock_audit.call_args.args[0], "project_member.removed")
        self.assertEqual(mock_audit.call_args.kwargs["metadata"]["from_role"], "developer")


if __name__ == "__main__":
    unittest.main()
