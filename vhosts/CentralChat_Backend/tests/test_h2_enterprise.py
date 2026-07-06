"""H2 — enterprise feature tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.shared.dlp_scanner import scan_prompt_text
from app.shared.policy_engine import requires_dual_approval, resolve_write_mode
from app.auth import map_role_from_oidc_payload


class H2PolicyTest(unittest.TestCase):
    def test_dual_approval_payment_path(self) -> None:
        self.assertTrue(requires_dual_approval("apps/payment/service.py"))

    def test_pr_only_in_production_env(self) -> None:
        with patch("app.config.CENTRAL_APP_ENV", "production"):
            mode = resolve_write_mode("src/foo.py", tenant_id="default")
        self.assertEqual(mode, "pr_only")


class H2DlpTest(unittest.TestCase):
    def test_blocks_aws_key_when_enabled(self) -> None:
        with patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True):
            r = scan_prompt_text("key AKIAIOSFODNN7EXAMPLE here")
        self.assertFalse(r.allowed)
        self.assertIn("aws_access_key", r.hits)


class H2OidcRoleTest(unittest.TestCase):
    def test_maps_group_to_role(self) -> None:
        with patch("app.config.CENTRAL_OIDC_GROUP_ROLE_MAP", {"central-admins": "admin"}):
            role = map_role_from_oidc_payload({"groups": ["central-admins"]})
        self.assertEqual(role, "admin")

    def test_maps_staging_group_map(self) -> None:
        """C1.3 — group→role com mapa tipo staging."""
        role_map = {
            "central-developers": "developer",
            "central-approvers": "approver",
            "central-admins": "admin",
            "central-auditors": "auditor",
            "central-viewers": "viewer",
        }
        with patch("app.config.CENTRAL_OIDC_GROUP_ROLE_MAP", role_map):
            self.assertEqual(
                map_role_from_oidc_payload({"groups": ["central-approvers"]}),
                "approver",
            )
            self.assertEqual(
                map_role_from_oidc_payload({"groups": ["central-auditors"]}),
                "auditor",
            )

    def test_oidc_exchange_role_in_response(self) -> None:
        """C1.3 — role do IdP exposta no par JWT após exchange."""
        from unittest.mock import patch as mock_patch

        from fastapi.testclient import TestClient

        _secret = "unit-test-secret________________"
        with (
            mock_patch("app.http.auth_routes.CENTRAL_OIDC_ENABLED", True),
            mock_patch("app.http.auth_routes.oidc_configured", return_value=True),
            mock_patch("app.http.auth_routes.is_allowed_redirect_uri", return_value=True),
            mock_patch("app.http.auth_routes.exchange_authorization_code", return_value={"id_token": "x"}),
            mock_patch(
                "app.http.auth_routes.resolve_identity_from_token_response",
                return_value=("sub-1", "default"),
            ),
            mock_patch(
                "app.http.auth_routes.resolve_oidc_profile_from_token_response",
                return_value={"email": "a@b.c", "display_name": "A", "role": "auditor"},
            ),
            mock_patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"),
            mock_patch("app.auth.CENTRAL_JWT_SECRET", _secret),
        ):
            from app.server import app

            r = TestClient(app).post(
                "/auth/oidc/exchange",
                json={
                    "code": "c" * 8,
                    "code_verifier": "v" * 43,
                    "redirect_uri": "http://localhost:5174/oidc-callback",
                },
            )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("role"), "auditor")


if __name__ == "__main__":
    unittest.main()
