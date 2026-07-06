"""Admin users API helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.auth import AuthUserRow, _normalize_auth_role, is_refresh_subject_revoked, revoke_user_refresh_sessions
import app.admin_routes as admin_routes


class AdminUsersTest(unittest.TestCase):
    def test_auth_role_base_and_legacy_policy(self) -> None:
        self.assertEqual(_normalize_auth_role("lead", allow_legacy=False), "lead")
        self.assertEqual(_normalize_auth_role("auditor", allow_legacy=False), "auditor")
        with self.assertRaises(ValueError):
            _normalize_auth_role("approver", allow_legacy=False)
        self.assertEqual(_normalize_auth_role("approver", allow_legacy=True), "approver")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "list_auth_users")
    def test_admin_users_list_shape(self, mock_list: MagicMock, *_m: object) -> None:
        mock_list.return_value = [
            AuthUserRow(
                id="00000000-0000-4000-8000-000000000001",
                email="dev@acme.test",
                client_id="acme",
                display_name="Dev",
                active=True,
                role="developer",
            )
        ]
        out = admin_routes.admin_users_list()
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["email"], "dev@acme.test")

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "_audit_admin_user")
    @patch.object(admin_routes, "create_admin_user")
    def test_admin_users_create_does_not_create_membership(self, mock_create: MagicMock, *_m: object) -> None:
        mock_create.return_value = AuthUserRow(
            id="00000000-0000-4000-8000-000000000001",
            email="dev@acme.test",
            client_id="acme",
            display_name="Dev",
            active=True,
            role="developer",
        )
        body = admin_routes.AdminUserCreateBody(
            email="dev@acme.test",
            password="secret123",
            display_name="Dev",
            role="developer",
        )
        out = admin_routes.admin_users_create(body)
        self.assertTrue(out["ok"])
        self.assertFalse(out["membership_created"])
        mock_create.assert_called_once()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "_audit_admin_user")
    @patch.object(admin_routes, "revoke_user_refresh_sessions")
    @patch.object(admin_routes, "update_admin_user")
    def test_admin_users_patch_shape(self, mock_update: MagicMock, mock_revoke: MagicMock, *_m: object) -> None:
        mock_update.return_value = AuthUserRow(
            id="00000000-0000-4000-8000-000000000001",
            email="lead@acme.test",
            client_id="acme",
            display_name="Lead",
            active=False,
            role="lead",
        )
        body = admin_routes.AdminUserPatchBody(display_name="Lead", role="lead", active=False)
        out = admin_routes.admin_users_patch("00000000-0000-4000-8000-000000000001", body)
        self.assertTrue(out["ok"])
        self.assertEqual(out["user"]["role"], "lead")
        self.assertFalse(out["user"]["active"])
        self.assertTrue(out["sessions_revoked"])
        mock_revoke.assert_called_once()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "get_current_sub", return_value="00000000-0000-4000-8000-000000000001")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "update_admin_user")
    def test_admin_users_patch_forbids_self_role_change(self, mock_update: MagicMock, *_m: object) -> None:
        body = admin_routes.AdminUserPatchBody(role="admin")
        with self.assertRaises(admin_routes.HTTPException) as ctx:
            admin_routes.admin_users_patch("00000000-0000-4000-8000-000000000001", body)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "self_role_change_forbidden")
        mock_update.assert_not_called()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "_audit_admin_user")
    @patch.object(admin_routes, "revoke_user_refresh_sessions")
    @patch.object(admin_routes, "reset_admin_user_password", return_value=True)
    def test_admin_users_reset_password_shape(self, mock_reset: MagicMock, mock_revoke: MagicMock, *_m: object) -> None:
        body = admin_routes.AdminUserResetPasswordBody(password="secret123")
        out = admin_routes.admin_users_reset_password("00000000-0000-4000-8000-000000000001", body)
        self.assertTrue(out["ok"])
        self.assertTrue(out["sessions_revoked"])
        mock_reset.assert_called_once()
        mock_revoke.assert_called_once()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "_audit_admin_user")
    @patch.object(admin_routes, "revoke_user_refresh_sessions")
    def test_admin_users_revoke_sessions_shape(self, mock_revoke: MagicMock, *_m: object) -> None:
        out = admin_routes.admin_users_revoke_sessions("00000000-0000-4000-8000-000000000001")
        self.assertTrue(out["ok"])
        self.assertTrue(out["sessions_revoked"])
        mock_revoke.assert_called_once()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "list_user_memberships")
    def test_admin_users_memberships_shape(self, mock_memberships: MagicMock, *_m: object) -> None:
        mock_memberships.return_value = [
            {
                "id": "m1",
                "tenant_id": "acme",
                "user_id": "00000000-0000-4000-8000-000000000001",
                "scope_type": "project",
                "scope_id": "00000000-0000-4000-8000-000000000010",
                "role": "developer",
            }
        ]
        out = admin_routes.admin_users_memberships("00000000-0000-4000-8000-000000000001")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["scope_type"], "project")

    def test_revoke_user_refresh_sessions_invalidates_older_refreshes(self) -> None:
        with patch("app.config.REFRESH_REVOCATIONS_STORE_PATH", "/tmp/test-central-refresh-revocations-admin-users.json"):
            revoke_user_refresh_sessions(
                user_id="00000000-0000-4000-8000-000000000001",
                revoked_after_unix=100,
            )
            self.assertTrue(
                is_refresh_subject_revoked(
                    sub="00000000-0000-4000-8000-000000000001",
                    iat_unix=99,
                )
            )
            self.assertFalse(
                is_refresh_subject_revoked(
                    sub="00000000-0000-4000-8000-000000000001",
                    iat_unix=101,
                )
            )


if __name__ == "__main__":
    unittest.main()
