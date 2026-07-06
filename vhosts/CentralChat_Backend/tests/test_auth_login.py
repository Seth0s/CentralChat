"""Fase A — POST /auth/login, public-config, logout."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from app.auth import AuthUserRow, reset_login_rate_limit_for_tests

_SECRET = "unit-test-secret________________"


class TestAuthLogin(unittest.TestCase):
    def tearDown(self) -> None:
        reset_login_rate_limit_for_tests()

    def test_public_config_jwt_off(self) -> None:
        with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "off"):
            from app.server import app

            r = TestClient(app).get("/auth/public-config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["jwt_mode"], "off")
        self.assertFalse(body["auth_login_enabled"])
        self.assertFalse(body["auth_refresh_enabled"])

    def test_login_disabled_when_jwt_off(self) -> None:
        with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "off"):
            from app.server import app

            r = TestClient(app).post(
                "/auth/login",
                json={"email": "a@b.co", "password": "secret"},
            )
        self.assertEqual(r.status_code, 404)

    @patch("app.http.auth_routes.auth_db_configured", return_value=True)
    @patch("app.http.auth_routes.verify_credentials")
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    @patch("app.http.auth_routes.AUTH_LOGIN_ENABLED", True)
    @patch("app.jwt_tokens.CENTRAL_JWT_SECRET", _SECRET)
    @patch("app.jwt_tokens.CENTRAL_JWT_ISSUER", "")
    @patch("app.jwt_tokens.CENTRAL_JWT_AUDIENCE", "")
    def test_login_success(self, mock_verify: object, *_m: object) -> None:
        mock_verify.return_value = (
            AuthUserRow(id="uid-1", email="u@acme.io", client_id="acme", active=True),
            None,
        )
        from app.server import app

        r = TestClient(app).post(
            "/auth/login",
            json={"email": "u@acme.io", "password": "good"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)
        payload = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], "uid-1")
        self.assertEqual(payload["client_id"], "acme")

    @patch("app.http.auth_routes.auth_db_configured", return_value=True)
    @patch("app.http.auth_routes.verify_credentials", return_value=(None, None))
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    @patch("app.http.auth_routes.AUTH_LOGIN_ENABLED", True)
    def test_login_invalid_credentials_problem_json(self, *_m: object) -> None:
        from app.server import app

        r = TestClient(app).post(
            "/auth/login",
            json={"email": "u@acme.io", "password": "bad"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertIn("application/problem+json", r.headers.get("content-type", ""))
        self.assertIn("invalid_credentials", r.json().get("type", ""))

    @patch("app.http.auth_routes.auth_db_configured", return_value=True)
    @patch("app.http.auth_routes.verify_credentials", return_value=(None, "account_disabled"))
    @patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required")
    @patch("app.http.auth_routes.AUTH_LOGIN_ENABLED", True)
    def test_login_account_disabled(self, *_m: object) -> None:
        from app.server import app

        r = TestClient(app).post(
            "/auth/login",
            json={"email": "u@acme.io", "password": "x"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertIn("account_disabled", r.json().get("type", ""))

    def test_logout_revokes_refresh(self) -> None:
        td = tempfile.mkdtemp()
        rev_path = Path(td) / "rev.json"
        with patch("app.config.REFRESH_REVOCATIONS_STORE_PATH", str(rev_path)):
            with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"):
                with patch("app.jwt_tokens.CENTRAL_JWT_SECRET", _SECRET):
                    with patch("app.jwt_tokens.CENTRAL_JWT_ISSUER", ""):
                        with patch("app.jwt_tokens.CENTRAL_JWT_AUDIENCE", ""):
                            from app.jwt_tokens import mint_token_pair
                            from app.server import app

                            pair = mint_token_pair(sub="u", client_id="c1")
                            refresh = pair["refresh_token"]
                            client = TestClient(app)
                            r0 = client.post("/auth/logout", json={"refresh_token": refresh})
                            self.assertEqual(r0.status_code, 200)
                            r1 = client.post("/auth/refresh", json={"refresh_token": refresh})
                            self.assertEqual(r1.status_code, 401)

    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required")
    @patch("app.jwt_tokens.CENTRAL_JWT_SECRET", _SECRET)
    @patch("app.jwt_tokens.CENTRAL_JWT_ISSUER", "")
    @patch("app.jwt_tokens.CENTRAL_JWT_AUDIENCE", "")
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id")
    def test_public_config_without_bearer(self, *_m: object) -> None:
        with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"):
            from app.server import app

            r = TestClient(app).get("/auth/public-config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["jwt_mode"], "required")


if __name__ == "__main__":
    unittest.main()
