"""Fase B — OIDC exchange + public-config."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "unit-test-secret________________"


class TestAuthOidc(unittest.TestCase):
    def tearDown(self) -> None:
        from app.auth import reset_oidc_discovery_cache_for_tests, reset_oidc_jwks_client_for_tests

        reset_oidc_discovery_cache_for_tests()
        reset_oidc_jwks_client_for_tests()

    @patch("app.http.auth_routes.CENTRAL_OIDC_ENABLED", True)
    @patch("app.http.auth_routes.oidc_configured", return_value=True)
    @patch("app.http.auth_routes.oidc_public_config")
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    def test_public_config_includes_oidc(self, mock_oidc_pub: object, *_m: object) -> None:
        mock_oidc_pub.return_value = {
            "authorization_endpoint": "https://idp.example/authorize",
            "client_id": "spa-client",
            "scopes": "openid profile email",
            "redirect_uri": "http://localhost:5173/",
        }
        from app.server import app

        r = TestClient(app).get("/auth/public-config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["auth_oidc_enabled"])
        self.assertIn("oidc", body)

    @patch("app.http.auth_routes.CENTRAL_OIDC_ENABLED", False)
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    def test_oidc_exchange_disabled(self) -> None:
        from app.server import app

        r = TestClient(app).post(
            "/auth/oidc/exchange",
            json={
                "code": "abcd",
                "code_verifier": "x" * 43,
                "redirect_uri": "http://localhost:5173/",
            },
        )
        self.assertEqual(r.status_code, 404, r.text)

    @patch("app.http.auth_routes.CENTRAL_OIDC_ENABLED", True)
    @patch("app.http.auth_routes.oidc_configured", return_value=True)
    @patch("app.http.auth_routes.is_allowed_redirect_uri", return_value=True)
    @patch("app.http.auth_routes.exchange_authorization_code")
    @patch("app.http.auth_routes.resolve_identity_from_token_response")
    @patch("app.http.auth_routes.resolve_oidc_profile_from_token_response")
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    @patch("app.auth.CENTRAL_JWT_SECRET", _SECRET)
    @patch("app.auth.CENTRAL_JWT_ISSUER", "")
    @patch("app.auth.CENTRAL_JWT_AUDIENCE", "")
    def test_oidc_exchange_mints_internal_jwt(
        self,
        mock_profile: object,
        mock_resolve: object,
        mock_exchange: object,
        *_m: object,
    ) -> None:
        mock_exchange.return_value = {"id_token": "dummy"}
        mock_resolve.return_value = ("oidc-sub-99", "tenant-a")
        mock_profile.return_value = {
            "email": "dev@example.com",
            "display_name": "Dev",
            "role": "developer",
        }
        from app.server import app

        r = TestClient(app).post(
            "/auth/oidc/exchange",
            json={
                "code": "auth-code-1",
                "code_verifier": "v" * 43,
                "redirect_uri": "http://localhost:5173/",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        payload = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], "oidc-sub-99")
        self.assertEqual(payload["client_id"], "tenant-a")

    def test_oidc_exchange_emits_audit_login(self) -> None:
        with (
            patch("app.http.auth_routes.CENTRAL_OIDC_ENABLED", True),
            patch("app.http.auth_routes.oidc_configured", return_value=True),
            patch("app.http.auth_routes.is_allowed_redirect_uri", return_value=True),
            patch(
                "app.http.auth_routes.exchange_authorization_code",
                return_value={"id_token": "dummy"},
            ),
            patch(
                "app.http.auth_routes.resolve_identity_from_token_response",
                return_value=("oidc-sub-99", "tenant-a"),
            ),
            patch(
                "app.http.auth_routes.resolve_oidc_profile_from_token_response",
                return_value={
                    "email": "approver@local.test",
                    "display_name": "Approver",
                    "role": "approver",
                },
            ),
            patch("app.audit_service.append_audit_event") as mock_audit,
            patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"),
            patch("app.auth.CENTRAL_JWT_SECRET", _SECRET),
            patch("app.auth.CENTRAL_JWT_ISSUER", ""),
            patch("app.auth.CENTRAL_JWT_AUDIENCE", ""),
        ):
            from app.server import app

            r = TestClient(app).post(
                "/auth/oidc/exchange",
                json={
                    "code": "auth-code-2",
                    "code_verifier": "v" * 43,
                    "redirect_uri": "http://localhost:5174/oidc-callback",
                },
            )
        self.assertEqual(r.status_code, 200, r.text)
        mock_audit.assert_called()
        actions = [c.kwargs.get("action") for c in mock_audit.call_args_list]
        self.assertIn("auth.oidc_login", actions)
        login_call = next(
            c for c in mock_audit.call_args_list if c.kwargs.get("action") == "auth.oidc_login"
        )
        self.assertEqual(login_call.kwargs.get("tenant_id"), "tenant-a")
        self.assertEqual(login_call.kwargs.get("metadata", {}).get("role"), "approver")

    @patch("app.audit_service.append_audit_event")
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    @patch("app.auth.CENTRAL_JWT_SECRET", _SECRET)
    def test_logout_emits_audit(self, mock_audit: object, *_m: object) -> None:
        from app.auth import mint_token_pair
        from app.server import app

        pair = mint_token_pair(sub="user-1", client_id="default", email="u@t.com")
        r = TestClient(app).post(
            "/auth/logout",
            json={"refresh_token": pair["refresh_token"]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        mock_audit.assert_called_once()
        self.assertEqual(mock_audit.call_args.kwargs.get("action"), "auth.logout")

    def test_hybrid_accepts_oidc_bearer(self) -> None:
        with (
            patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "hybrid"),
            patch("app.shared.pg_tenant.memory_db_enabled", return_value=False),
            patch("app.http.auth_context_middleware.decode_access_token") as mock_decode,
        ):
            mock_decode.return_value = {
                "sub": "ext-user",
                "client_id": "ext-tenant",
                "exp": int(time.time()) + 3600,
                "typ": "access",
            }
            from app.server import app

            client = TestClient(app)
            r = client.get("/config", headers={"Authorization": "Bearer external.jwt"})
        self.assertEqual(r.status_code, 200)
        mock_decode.assert_called_once()
