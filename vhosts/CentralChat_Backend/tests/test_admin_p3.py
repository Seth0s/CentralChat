"""P3 — session ACL, team requests and work item collaboration tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.admin_routes as admin_routes
from app.session_acl import user_can_access_session


class SessionAclTest(unittest.TestCase):
    def test_user_role_acl_grants_access(self) -> None:
        entries = [
            {
                "principal_type": "user",
                "principal_id": "00000000-0000-4000-8000-000000000099",
            }
        ]
        with patch("app.session_acl.list_session_acl", return_value=entries):
            allowed = user_can_access_session(
                session_id="sess-1",
                role="developer",
                user_id="00000000-0000-4000-8000-000000000099",
            )
        self.assertTrue(allowed)

    def test_role_acl_grants_access(self) -> None:
        entries = [{"principal_type": "role", "principal_id": "developer"}]
        with patch("app.session_acl.list_session_acl", return_value=entries):
            allowed = user_can_access_session(
                session_id="sess-1",
                role="developer",
                user_id="00000000-0000-4000-8000-000000000001",
            )
        self.assertTrue(allowed)

    def test_lead_bypasses_acl(self) -> None:
        with patch("app.session_acl.list_session_acl", return_value=[]):
            allowed = user_can_access_session(
                session_id="sess-1",
                role="lead",
                user_id="00000000-0000-4000-8000-000000000001",
            )
        self.assertTrue(allowed)

    def test_developer_without_acl_denied(self) -> None:
        with patch("app.session_acl.list_session_acl", return_value=[]):
            allowed = user_can_access_session(
                session_id="sess-1",
                role="developer",
                user_id="00000000-0000-4000-8000-000000000001",
            )
        self.assertFalse(allowed)

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "get_current_role", return_value="lead")
    @patch.object(admin_routes, "get_current_sub", return_value="lead-1")
    @patch.object(admin_routes, "user_can_access_session", return_value=True)
    @patch.object(admin_routes, "get_session")
    def test_admin_session_detail_shape(self, mock_get_session: MagicMock, *_m: object) -> None:
        mock_get_session.return_value = {"id": "sess-1", "title": "Demo"}
        out = admin_routes.admin_session_detail("sess-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["session"]["id"], "sess-1")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "memory_db_enabled", return_value=True)
    @patch.object(admin_routes, "upsert_session_acl")
    @patch.object(admin_routes, "append_audit_event")
    @patch.object(admin_routes, "get_current_sub", return_value="lead-1")
    def test_admin_session_acl_upsert_audited(
        self,
        mock_audit: MagicMock,
        mock_upsert: MagicMock,
        *_m: object,
    ) -> None:
        mock_upsert.return_value = {
            "session_id": "sess-1",
            "principal_type": "user",
            "principal_id": "dev-1",
            "access_level": "read",
        }
        body = admin_routes.SessionAclUpsertBody(
            principal_type="user",
            principal_id="dev-1",
            access_level="read",
        )
        out = admin_routes.admin_session_acl_upsert("sess-1", body)
        self.assertTrue(out["ok"])
        mock_audit.assert_called_once()


class TeamRequestsAdminTest(unittest.TestCase):
    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "memory_db_enabled", return_value=True)
    @patch.object(admin_routes, "find_project_lead_user_id", return_value="lead-uuid")
    @patch.object(admin_routes, "create_team_request")
    def test_admin_requests_create_assigns_project_lead(
        self,
        mock_create: MagicMock,
        mock_find_lead: MagicMock,
        *_m: object,
    ) -> None:
        mock_create.return_value = {"id": "req-1", "assignee_id": "lead-uuid"}
        body = admin_routes.TeamRequestCreateBody(
            request_type="lead_decision",
            title="Need approval",
            project_id="00000000-0000-4000-8000-000000000010",
        )
        out = admin_routes.admin_requests_create(body)
        self.assertTrue(out["ok"])
        mock_find_lead.assert_called_once()
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args.kwargs["assignee_id"], "lead-uuid")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "memory_db_enabled", return_value=True)
    @patch.object(admin_routes, "resolve_team_request")
    def test_admin_requests_resolve_shape(self, mock_resolve: MagicMock, *_m: object) -> None:
        mock_resolve.return_value = {"id": "req-1", "status": "resolved"}
        body = admin_routes.TeamRequestResolveBody(resolution="Approved for staging")
        out = admin_routes.admin_requests_resolve("req-1", body)
        self.assertTrue(out["ok"])
        self.assertEqual(out["request"]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
