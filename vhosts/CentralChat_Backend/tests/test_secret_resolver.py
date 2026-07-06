"""Tests for secret_resolver (Phase 0 integration secrets)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.shared.secret_backends import reset_secret_backend_cache
from app.shared.secret_resolver import (
    resolve_alert_webhook_urls,
    resolve_integration_secret,
    resolve_quota_webhook_url,
    resolve_siem_hec_token,
    resolve_siem_webhook_urls,
)


class SecretResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_secret_backend_cache()
        import app.shared.inference_governance as ig

        ig._migrated_legacy_vault = False
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "secrets" / "values").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        reset_secret_backend_cache()

    def _patches(self):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("app.shared.secrets_admin.CENTRAL_ROOT", str(self.root)))
        stack.enter_context(patch("app.shared.inference_governance.CENTRAL_ROOT", str(self.root)))
        stack.enter_context(patch("app.config.CENTRAL_ROOT", str(self.root)))
        stack.enter_context(patch("app.shared.inference_governance.OPENROUTER_API_KEY", ""))
        stack.enter_context(patch("app.shared.inference_governance.CENTRAL_CLOUD_MODEL_ALLOWLIST", ()))
        stack.enter_context(patch("app.shared.secret_refs_store.memory_db_enabled", return_value=False))
        return stack

    def test_env_wins_over_vault(self) -> None:
        with self._patches():
            from app.shared.secrets_admin import upsert_secret

            upsert_secret("alert.webhook", value="https://vault.example/hook")
            with patch("app.shared.secret_resolver.CENTRAL_ALERT_WEBHOOK_URL", "https://env.example/hook"):
                self.assertEqual(
                    resolve_integration_secret("alert.webhook", env_value="https://env.example/hook"),
                    "https://env.example/hook",
                )
                self.assertIn("https://env.example/hook", resolve_alert_webhook_urls())

    def test_siem_webhook_from_custom_secret(self) -> None:
        with self._patches():
            from app.shared.secrets_admin import upsert_secret

            with patch("app.shared.secret_resolver.CENTRAL_SIEM_WEBHOOK_URLS", ()):
                upsert_secret(
                    "siem.webhook",
                    value="https://siem-a.example, https://siem-b.example",
                )
                urls = resolve_siem_webhook_urls()
        self.assertEqual(urls, ("https://siem-a.example", "https://siem-b.example"))

    def test_quota_webhook_fallback(self) -> None:
        with self._patches():
            from app.shared.secrets_admin import upsert_secret

            with patch("app.shared.secret_resolver.CENTRAL_QUOTA_WEBHOOK_URL", ""):
                upsert_secret("quota.webhook", value="https://quota.example/alert")
                self.assertEqual(resolve_quota_webhook_url(), "https://quota.example/alert")

    def test_siem_hec_token_fallback(self) -> None:
        with self._patches():
            from app.shared.secrets_admin import upsert_secret

            with patch("app.shared.secret_resolver.CENTRAL_SIEM_HEC_TOKEN", ""):
                upsert_secret("siem.hec_token", value="hec-token-123")
                self.assertEqual(resolve_siem_hec_token(), "hec-token-123")


if __name__ == "__main__":
    unittest.main()
