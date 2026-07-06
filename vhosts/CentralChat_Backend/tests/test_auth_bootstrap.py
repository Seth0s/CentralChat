"""Bootstrap admin and forced password change (GitLab-style startup)."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "bootstrap-test-secret_____________"


class TestAuthBootstrap(unittest.TestCase):
    def test_validate_new_password(self) -> None:
        from app.auth import validate_new_password

        validate_new_password("long-enough")
        with self.assertRaises(ValueError):
            validate_new_password("short")

    @patch("app.auth.ensure_auth_schema")
    @patch("app.auth.CENTRAL_BOOTSTRAP_ADMIN_ENABLED", True)
    @patch("app.auth.auth_db_configured", return_value=True)
    @patch("app.auth.count_auth_users", return_value=1)
    def test_ensure_bootstrap_skips_when_users_exist(self, *_m: object) -> None:
        from app.auth import ensure_bootstrap_admin

        self.assertIsNone(ensure_bootstrap_admin())

    @patch("app.auth.CENTRAL_BOOTSTRAP_ADMIN_ENABLED", False)
    @patch("app.auth.auth_db_configured", return_value=True)
    def test_ensure_bootstrap_disabled(self, *_m: object) -> None:
        from app.auth import ensure_bootstrap_admin

        self.assertIsNone(ensure_bootstrap_admin())


class TestPasswordChangeRequired(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = [
            patch("app.http.auth_context_middleware.CENTRAL_JWT_MODE", "required"),
            patch("app.auth.CENTRAL_JWT_SECRET", _SECRET),
            patch("app.auth.CENTRAL_JWT_ISSUER", ""),
            patch("app.auth.CENTRAL_JWT_AUDIENCE", ""),
            patch("app.http.auth_context_middleware.CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id"),
        ]
        for p in self._patches:
            p.start()
        from app.server import app

        self.client = TestClient(app)

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _token(self, *, must_change: bool = True) -> str:
        now = int(time.time())
        body = {
            "sub": "00000000-0000-4000-8000-000000000099",
            "client_id": "default",
            "role": "admin",
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        }
        if must_change:
            body["must_change_password"] = True
        return jwt.encode(body, _SECRET, algorithm="HS256")

    def test_blocks_admin_route_until_password_changed(self) -> None:
        r = self.client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertIn("password_change_required", r.json().get("type", ""))

    def test_allows_change_password_route(self) -> None:
        with patch("app.auth.change_user_password") as mock_change:
            mock_change.return_value = MagicMock(
                id="00000000-0000-4000-8000-000000000099",
                email="root@central.local",
                client_id="default",
                display_name="root",
                active=True,
                role="admin",
                must_change_password=False,
            )
            r = self.client.post(
                "/auth/change-password",
                headers={"Authorization": f"Bearer {self._token()}"},
                json={
                    "current_password": "changeme",
                    "new_password": "new-secret-1",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get("must_change_password", True))
        self.assertIn("access_token", r.json())


if __name__ == "__main__":
    unittest.main()
