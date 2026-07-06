"""Fase 4 — JWT Bearer + refresh rotation."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "unit-test-secret________________"


def _access_token(client_id: str = "acme-1") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "user1",
            "client_id": client_id,
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )


class TestJwtAuthTenant(unittest.TestCase):
    def test_refresh_off_returns_404(self) -> None:
        with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "off"):
            from app.server import app

            client = TestClient(app)
            r = client.post("/auth/refresh", json={"refresh_token": "x" * 20})
            self.assertEqual(r.status_code, 404)

    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required")
    @patch("app.auth.CENTRAL_JWT_SECRET", _SECRET)
    @patch("app.auth.CENTRAL_JWT_ISSUER", "")
    @patch("app.auth.CENTRAL_JWT_AUDIENCE", "")
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id")
    def test_required_missing_bearer_401(self) -> None:
        from app.server import app

        client = TestClient(app)
        r = client.get("/config")
        self.assertEqual(r.status_code, 401)
        self.assertIn("application/problem+json", r.headers.get("content-type", ""))

    @patch("app.config.CENTRAL_ROOT", tempfile.mkdtemp())
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required")
    @patch("app.auth.CENTRAL_JWT_SECRET", _SECRET)
    @patch("app.auth.CENTRAL_JWT_ISSUER", "")
    @patch("app.auth.CENTRAL_JWT_AUDIENCE", "")
    @patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id")
    def test_required_valid_bearer_allows_config(self) -> None:
        from app.server import app

        tok = _access_token()
        client = TestClient(app)
        r = client.get("/approvals", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(r.status_code, 200)

    def test_refresh_rotation_second_call_401(self) -> None:
        td = tempfile.mkdtemp()
        rev_path = Path(td) / "rev.json"
        with patch("app.config.REFRESH_REVOCATIONS_STORE_PATH", str(rev_path)):
            with patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"):
                with patch("app.auth.CENTRAL_JWT_SECRET", _SECRET):
                    with patch("app.auth.CENTRAL_JWT_ISSUER", ""):
                        with patch("app.auth.CENTRAL_JWT_AUDIENCE", ""):
                            from app.auth import mint_token_pair
                            from app.server import app

                            pair = mint_token_pair(sub="u", client_id="c1")
                            refresh1 = pair["refresh_token"]
                            client = TestClient(app)
                            r1 = client.post("/auth/refresh", json={"refresh_token": refresh1})
                            self.assertEqual(r1.status_code, 200, r1.text)
                            r2 = client.post("/auth/refresh", json={"refresh_token": refresh1})
                            self.assertEqual(r2.status_code, 401)


if __name__ == "__main__":
    unittest.main()
