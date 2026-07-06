"""ADR-015 — OIDC id_token validation and production policy."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import jwt

from app.oidc_tenant import resolve_tenant_client_id


class TestOidcTenant(unittest.TestCase):
    @patch("app.oidc_tenant.CENTRAL_OIDC_STRICT_TENANT", True)
    @patch("app.oidc_tenant.CENTRAL_OIDC_TENANT_CLAIM", "")
    @patch("app.oidc_tenant.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id")
    def test_strict_requires_tenant_claim(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_tenant_client_id({"sub": "u1"})
        self.assertEqual(str(ctx.exception), "tenant_not_provisioned")

    @patch("app.oidc_tenant.CENTRAL_OIDC_STRICT_TENANT", False)
    @patch("app.oidc_tenant.CENTRAL_DEFAULT_CLIENT_ID", "default")
    @patch("app.oidc_tenant.CENTRAL_OIDC_TENANT_CLAIM", "")
    @patch("app.oidc_tenant.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id")
    def test_non_strict_uses_default(self) -> None:
        self.assertEqual(resolve_tenant_client_id({"sub": "u1"}), "default")


class TestOidcIssuer(unittest.TestCase):
    def tearDown(self) -> None:
        from app.oidc_discovery import reset_oidc_discovery_cache_for_tests

        reset_oidc_discovery_cache_for_tests()

    @patch("app.oidc_discovery.CENTRAL_OIDC_ISSUER_URL", "http://localhost:8180/realms/central")
    @patch(
        "app.oidc_discovery.fetch_discovery_document",
        return_value={"issuer": "http://localhost:8080/realms/central"},
    )
    def test_valid_issuers_include_configured_and_discovery(self, _doc: object) -> None:
        from app.oidc_discovery import get_oidc_valid_issuers

        self.assertEqual(
            get_oidc_valid_issuers(),
            (
                "http://localhost:8180/realms/central",
                "http://localhost:8080/realms/central",
            ),
        )


class TestOidcUrls(unittest.TestCase):
    @patch("app.oidc_urls.CENTRAL_OIDC_HTTP_BASE", "http://central-keycloak-dev:8080")
    @patch("app.oidc_urls.CENTRAL_OIDC_ISSUER_URL", "http://localhost:8180/realms/central")
    def test_server_url_rewrites_internal_host(self) -> None:
        from app.oidc_urls import idp_url_for_server

        url = "http://localhost:8080/realms/central/protocol/openid-connect/token"
        out = idp_url_for_server(url)
        self.assertEqual(
            out,
            "http://central-keycloak-dev:8080/realms/central/protocol/openid-connect/token",
        )

    @patch("app.oidc_urls.CENTRAL_OIDC_ISSUER_URL", "http://localhost:8180/realms/central")
    def test_browser_url_rewrites_port(self) -> None:
        from app.oidc_urls import idp_url_for_browser

        url = "http://localhost:8080/realms/central/protocol/openid-connect/auth"
        out = idp_url_for_browser(url)
        self.assertIn(":8180", out)


class TestIdTokenAudience(unittest.TestCase):
    def test_audience_matches_client_via_azp(self) -> None:
        from app.oidc_jwks import _audience_matches_client

        self.assertTrue(
            _audience_matches_client({"aud": "account", "azp": "central-bff"}, "central-bff")
        )
        self.assertTrue(
            _audience_matches_client({"aud": ["central-bff", "account"]}, "central-bff")
        )
        self.assertFalse(_audience_matches_client({"aud": "account", "azp": "other"}, "central-bff"))


class TestDecodeIdToken(unittest.TestCase):
    def tearDown(self) -> None:
        from app.oidc_jwks import reset_oidc_jwks_client_for_tests

        reset_oidc_jwks_client_for_tests()

    @patch("app.oidc_jwks.jwt.decode")
    @patch("app.oidc_jwks._jwks_client")
    @patch(
        "app.oidc_jwks.get_oidc_valid_issuers",
        return_value=("https://idp.example/realms/r1",),
    )
    @patch("app.oidc_jwks.CENTRAL_OIDC_CLIENT_ID", "bff-client")
    def test_decode_id_token_uses_client_id_as_audience(
        self,
        _iss: object,
        mock_jwks: object,
        mock_decode: object,
    ) -> None:
        mock_jwks.return_value.get_signing_key_from_jwt.return_value = MagicMock(key="secret")
        mock_decode.return_value = {"sub": "user-1", "aud": "bff-client"}

        from app.oidc_jwks import decode_id_token

        payload = decode_id_token("header.payload.sig")
        self.assertEqual(payload["sub"], "user-1")
        _args, kwargs = mock_decode.call_args
        self.assertEqual(kwargs.get("audience"), "bff-client")
        self.assertEqual(kwargs.get("issuer"), "https://idp.example/realms/r1")

    @patch("app.oidc_jwks.CENTRAL_OIDC_CLIENT_ID", "central-bff")
    @patch("app.oidc_jwks._decode_with_jwks")
    def test_decode_id_token_accepts_keycloak_aud_account_via_azp(self, mock_decode: object) -> None:
        from app.oidc_jwks import decode_id_token

        mock_decode.side_effect = [
            jwt.InvalidAudienceError("aud mismatch"),
            {"sub": "u1", "aud": "account", "azp": "central-bff"},
        ]
        payload = decode_id_token("tok")
        self.assertEqual(payload["sub"], "u1")
        self.assertEqual(mock_decode.call_count, 2)


class TestAuthProductionPolicy(unittest.TestCase):
    def test_production_rejects_hybrid(self) -> None:
        from app.auth_production_policy import validate_auth_production_policy

        with (
            patch("app.auth_production_policy.CENTRAL_APP_ENV", "production"),
            patch("app.auth_production_policy.CENTRAL_JWT_MODE", "hybrid"),
            patch("app.auth_production_policy.CENTRAL_OIDC_ENABLED", True),
            patch("app.auth_production_policy.AUTH_LOGIN_ENABLED", False),
        ):
            with self.assertRaises(RuntimeError):
                validate_auth_production_policy()

    def test_production_rejects_password_login(self) -> None:
        from app.auth_production_policy import validate_auth_production_policy

        with (
            patch("app.auth_production_policy.CENTRAL_APP_ENV", "production"),
            patch("app.auth_production_policy.CENTRAL_JWT_MODE", "required"),
            patch("app.auth_production_policy.CENTRAL_OIDC_ENABLED", True),
            patch("app.auth_production_policy.AUTH_LOGIN_ENABLED", True),
        ):
            with self.assertRaises(RuntimeError):
                validate_auth_production_policy()
