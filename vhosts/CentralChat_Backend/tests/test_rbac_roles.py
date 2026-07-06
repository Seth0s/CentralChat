"""Onda A — RBAC role gates (unit, no live stack)."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "rbac-test-secret________________"


def _token(*, sub: str = "u1", role: str = "developer", client_id: str = "default") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "client_id": client_id,
            "role": role,
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )


class TestRbacRoles(unittest.TestCase):
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

    def test_viewer_cannot_export_audit(self) -> None:
        r = self.client.get(
            "/admin/audit/export",
            headers={"Authorization": f"Bearer {_token(role='viewer')}"},
        )
        self.assertEqual(r.status_code, 403)

    def test_auditor_can_export_audit(self) -> None:
        r = self.client.get(
            "/admin/audit/export",
            headers={"Authorization": f"Bearer {_token(role='auditor')}"},
        )
        self.assertIn(r.status_code, (200, 503))

    def test_collaboration_roles_are_valid(self) -> None:
        from app.shared.rbac import VALID_ROLES, ROLE_RANK

        self.assertIn("reviewer", VALID_ROLES)
        self.assertIn("lead", VALID_ROLES)
        self.assertGreaterEqual(ROLE_RANK["reviewer"], ROLE_RANK["developer"])
        self.assertGreaterEqual(ROLE_RANK["lead"], ROLE_RANK["approver"])


if __name__ == "__main__":
    unittest.main()
