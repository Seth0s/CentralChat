"""Onda A — tenant isolation via JWT + HTTP (client_id claim)."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

_SECRET = "tenant-iso-secret_______________"


def _token(*, sub: str = "u1", client_id: str = "tenant-a") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "client_id": client_id,
            "role": "developer",
            "iat": now,
            "exp": now + 3600,
            "typ": "access",
        },
        _SECRET,
        algorithm="HS256",
    )


class TestTenantIsolationHttp(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self._patches = [
            patch("app.config.CENTRAL_ROOT", self.tmp.name),
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
        self.tmp.cleanup()

    def test_approval_created_in_tenant_a_not_visible_to_tenant_b(self) -> None:
        tok_a = _token(client_id="tenant-a")
        create = self.client.post(
            "/approvals/test",
            headers={"Authorization": f"Bearer {tok_a}"},
            json={"action_id": "test.echo", "payload": {"hello": "a"}},
        )
        self.assertEqual(create.status_code, 200, create.text)
        approval_id = create.json()["approval_id"]

        list_a = self.client.get(
            "/approvals",
            headers={"Authorization": f"Bearer {tok_a}"},
        )
        self.assertEqual(list_a.status_code, 200)
        ids_a = {it["approval_id"] for it in list_a.json().get("items") or []}
        self.assertIn(approval_id, ids_a)

        tok_b = _token(client_id="tenant-b", sub="u2")
        get_b = self.client.get(
            f"/approvals/{approval_id}/diff",
            headers={"Authorization": f"Bearer {tok_b}"},
        )
        self.assertIn(get_b.status_code, (404, 403))

        list_b = self.client.get(
            "/approvals",
            headers={"Authorization": f"Bearer {tok_b}"},
        )
        self.assertEqual(list_b.status_code, 200)
        ids_b = {it["approval_id"] for it in list_b.json().get("items") or []}
        self.assertNotIn(approval_id, ids_b)


if __name__ == "__main__":
    unittest.main()
