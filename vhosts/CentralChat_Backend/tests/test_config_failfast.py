"""Onda A — fail-fast when .env is incoherent."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestConfigFailFast(unittest.TestCase):
    def test_missing_db_url_with_login_enabled_fails(self) -> None:
        from app.config import validate_runtime_config

        with patch("app.config.AUTH_LOGIN_ENABLED", True):
            with patch("app.config.MEMORY_DB_URL", ""):
                with patch("app.config.AUTH_USERS_DB_URL", ""):
                    with self.assertRaises(RuntimeError) as ctx:
                        validate_runtime_config()
        self.assertIn("MEMORY_DB_URL", str(ctx.exception))

    def test_staging_without_jwt_fails(self) -> None:
        from app.config import validate_runtime_config

        with patch("app.config.CENTRAL_APP_ENV", "staging"):
            with patch("app.config.CENTRAL_JWT_MODE", "off"):
                with self.assertRaises(RuntimeError) as ctx:
                    validate_runtime_config()
        self.assertIn("JWT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
