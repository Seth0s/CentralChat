"""Organization scope memberships."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.org_memberships as org


class OrgMembershipsTest(unittest.TestCase):
    def test_slugify_and_validate_scope(self) -> None:
        self.assertEqual(org._normalize_slug(None, fallback="Frontend Platform"), "frontend-platform")
        self.assertEqual(org._normalize_scope_type("project"), "project")
        self.assertEqual(org._normalize_role("lead"), "lead")
        with self.assertRaises(ValueError):
            org._normalize_scope_type("ministry")
        with self.assertRaises(ValueError):
            org._normalize_role("approver")

    def test_upsert_project_membership_uses_scope_type_and_project_id(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        user_id = "00000000-0000-4000-8000-000000000011"
        with patch.object(org, "memory_db_enabled", return_value=True):
            with patch.object(org, "ensure_org_schema"):
                with patch.object(org, "get_project", return_value={"id": project_id}):
                    with patch.object(org, "_current_user_id", return_value="00000000-0000-4000-8000-000000000001"):
                        mock_conn = MagicMock()
                        mock_cur = MagicMock()
                        mock_cur.fetchone.return_value = (
                            "m1",
                            "acme",
                            user_id,
                            "project",
                            project_id,
                            "developer",
                            "00000000-0000-4000-8000-000000000001",
                            "now",
                            "now",
                        )
                        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
                        with patch.object(org, "connect_pg") as mock_pg:
                            mock_pg.return_value.__enter__.return_value = mock_conn
                            out = org.upsert_membership(
                                user_id=user_id,
                                scope_type="project",
                                scope_id=project_id,
                                role="developer",
                                tenant_id="acme",
                            )

        self.assertEqual(out["scope_type"], "project")
        self.assertEqual(out["scope_id"], project_id)
        self.assertEqual(out["role"], "developer")
        mock_pg.assert_called_with(tenant_id="acme")
        sql, params = mock_cur.execute.call_args.args
        self.assertIn("INSERT INTO memberships", sql)
        self.assertEqual(params[2], "project")
        self.assertEqual(params[3], project_id)

    def test_non_admin_lead_can_manage_project_via_group_membership(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        group_id = "00000000-0000-4000-8000-000000000020"
        with patch.object(org, "_is_global_admin", return_value=False):
            with patch.object(org, "_current_user_id", return_value="00000000-0000-4000-8000-000000000001"):
                with patch.object(
                    org,
                    "_fetch_memberships",
                    return_value=[
                        {
                            "scope_type": "group",
                            "scope_id": group_id,
                            "role": "lead",
                        }
                    ],
                ):
                    with patch.object(org, "_project_group_id", return_value=group_id):
                        self.assertTrue(org.can_manage_project(tenant_id="acme", project_id=project_id))

    def test_non_member_cannot_manage_project(self) -> None:
        project_id = "00000000-0000-4000-8000-000000000010"
        with patch.object(org, "_is_global_admin", return_value=False):
            with patch.object(org, "_current_user_id", return_value="00000000-0000-4000-8000-000000000001"):
                with patch.object(org, "_fetch_memberships", return_value=[]):
                    with patch.object(org, "_project_group_id", return_value=None):
                        self.assertFalse(org.can_manage_project(tenant_id="acme", project_id=project_id))

    def test_cannot_remove_last_direct_project_lead(self) -> None:
        with patch.object(org, "_project_membership_role", return_value="lead"):
            with patch.object(org, "_project_direct_lead_count", return_value=1):
                with self.assertRaises(ValueError) as ctx:
                    org._assert_not_removing_last_project_lead(
                        tenant_id="acme",
                        project_id="00000000-0000-4000-8000-000000000010",
                        user_id="00000000-0000-4000-8000-000000000011",
                        next_role="developer",
                    )
        self.assertEqual(str(ctx.exception), "last_project_lead")

    def test_can_keep_or_replace_when_other_project_leads_exist(self) -> None:
        with patch.object(org, "_project_membership_role", return_value="lead"):
            with patch.object(org, "_project_direct_lead_count", return_value=1):
                org._assert_not_removing_last_project_lead(
                    tenant_id="acme",
                    project_id="00000000-0000-4000-8000-000000000010",
                    user_id="00000000-0000-4000-8000-000000000011",
                    next_role="lead",
                )
        with patch.object(org, "_project_membership_role", return_value="lead"):
            with patch.object(org, "_project_direct_lead_count", return_value=2):
                org._assert_not_removing_last_project_lead(
                    tenant_id="acme",
                    project_id="00000000-0000-4000-8000-000000000010",
                    user_id="00000000-0000-4000-8000-000000000011",
                    next_role=None,
                )

    def test_list_user_memberships_filters_to_lead_scope(self) -> None:
        user_id = "00000000-0000-4000-8000-000000000011"
        managed_project = "00000000-0000-4000-8000-000000000010"
        other_project = "00000000-0000-4000-8000-000000000012"
        with patch.object(org, "get_current_sub", return_value="00000000-0000-4000-8000-000000000001"):
            with patch.object(org, "get_current_role", return_value="lead"):
                with patch.object(
                    org,
                    "_current_memberships",
                    return_value=[
                        {
                            "scope_type": "project",
                            "scope_id": managed_project,
                            "role": "lead",
                        }
                    ],
                ):
                    with patch.object(
                        org,
                        "_fetch_memberships",
                        return_value=[
                            {
                                "scope_type": "project",
                                "scope_id": managed_project,
                                "role": "developer",
                            },
                            {
                                "scope_type": "project",
                                "scope_id": other_project,
                                "role": "developer",
                            },
                        ],
                    ):
                        with patch.object(org, "_project_group_id", return_value=None):
                            out = org.list_user_memberships(user_id=user_id, tenant_id="acme")

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["scope_id"], managed_project)

    def test_list_org_health_flags_empty_groups_and_projects_without_lead(self) -> None:
        group_empty = "00000000-0000-4000-8000-000000000020"
        group_with_project = "00000000-0000-4000-8000-000000000021"
        project_without_lead = "00000000-0000-4000-8000-000000000030"
        project_with_lead = "00000000-0000-4000-8000-000000000031"
        with patch.object(
            org,
            "list_org_tree",
            return_value={
                "tenant_id": "acme",
                "groups": [
                    {"id": group_empty, "name": "Empty"},
                    {"id": group_with_project, "name": "Platform"},
                ],
                "projects": [
                    {"id": project_without_lead, "group_id": group_with_project, "name": "API"},
                    {"id": project_with_lead, "group_id": group_with_project, "name": "UI"},
                ],
            },
        ):
            with patch.object(
                org,
                "_project_direct_lead_count",
                side_effect=lambda **kwargs: 1 if kwargs["project_id"] == project_with_lead else 0,
            ):
                out = org.list_org_health(tenant_id="acme")

        self.assertEqual(out["counts"]["groups_without_projects"], 1)
        self.assertEqual(out["counts"]["projects_without_direct_lead"], 1)
        self.assertEqual(out["groups_without_projects"][0]["id"], group_empty)
        self.assertEqual(out["projects_without_direct_lead"][0]["id"], project_without_lead)


if __name__ == "__main__":
    unittest.main()
