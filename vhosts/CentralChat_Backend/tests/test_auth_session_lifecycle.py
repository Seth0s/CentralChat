"""Onda A — refresh rotation stress + logout revocation."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_SECRET = "lifecycle-test-secret____________"


class TestAuthSessionLifecycle(unittest.TestCase):
    def _client(self) -> TestClient:
        from app.server import app

        return TestClient(app)

    def _patches(self, rev_path: Path):
        return [
            patch("app.config.REFRESH_REVOCATIONS_STORE_PATH", str(rev_path)),
            patch("app.http.auth_routes.CENTRAL_JWT_MODE", "required"),
            patch("app.auth.CENTRAL_JWT_SECRET", _SECRET),
            patch("app.auth.CENTRAL_JWT_ISSUER", ""),
            patch("app.auth.CENTRAL_JWT_AUDIENCE", ""),
        ]

    def test_refresh_rotation_stress_old_jti_always_rejected(self) -> None:
        td = tempfile.mkdtemp()
        rev_path = Path(td) / "rev.json"
        with patch.multiple("app.config", REFRESH_REVOCATIONS_STORE_PATH=str(rev_path)):
            patches = self._patches(rev_path)
            for p in patches:
                p.start()
            try:
                from app.auth import mint_token_pair

                pair = mint_token_pair(sub="stress-user", client_id="default")
                refresh = pair["refresh_token"]
                client = self._client()
                used: list[str] = [refresh]

                for _ in range(8):
                    r = client.post("/auth/refresh", json={"refresh_token": refresh})
                    self.assertEqual(r.status_code, 200, r.text)
                    refresh = r.json()["refresh_token"]
                    used.append(refresh)

                for old in used[:-1]:
                    r_old = client.post("/auth/refresh", json={"refresh_token": old})
                    self.assertEqual(r_old.status_code, 401, old[:20])
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_logout_revokes_refresh_token(self) -> None:
        td = tempfile.mkdtemp()
        rev_path = Path(td) / "rev.json"
        with patch.multiple("app.config", REFRESH_REVOCATIONS_STORE_PATH=str(rev_path)):
            patches = self._patches(rev_path)
            for p in patches:
                p.start()
            try:
                from app.auth import mint_token_pair

                pair = mint_token_pair(sub="logout-user", client_id="default")
                refresh = pair["refresh_token"]
                client = self._client()

                logout = client.post("/auth/logout", json={"refresh_token": refresh})
                self.assertEqual(logout.status_code, 200)

                again = client.post("/auth/refresh", json={"refresh_token": refresh})
                self.assertEqual(again.status_code, 401)
            finally:
                for p in reversed(patches):
                    p.stop()


if __name__ == "__main__":
    unittest.main()
