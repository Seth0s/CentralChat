"""Admin secrets API tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app.admin_routes as admin_routes
from app.shared.secret_backends import reset_secret_backend_cache
from app.shared.secrets_admin import delete_secret, list_secrets_metadata, upsert_secret


class AdminSecretsTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_secret_backend_cache()
        import app.shared.inference_governance as ig

        ig._migrated_legacy_vault = False
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "config").mkdir()
        (self.root / "secrets").mkdir()

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

    def test_list_secrets_never_returns_raw_value(self) -> None:
        with self._patches():
            upsert_secret(
                "siem.webhook",
                value="whsec_super_secret_value",
                label="SIEM",
                category="webhook",
                updated_by="admin-1",
            )
            items = list_secrets_metadata()
        webhook = next(item for item in items if item["key"] == "siem.webhook")
        self.assertEqual(webhook["prefix"], "whse…")
        self.assertNotIn("super_secret_value", str(items))

    def test_provider_secret_rotation_metadata(self) -> None:
        with self._patches():
            item = upsert_secret(
                "provider:anthropic",
                value="sk-ant-test-key",
                updated_by="admin-1",
            )
        self.assertEqual(item["key"], "provider:anthropic")
        self.assertTrue(item["configured"])
        self.assertEqual(item["prefix"], "sk-a…")

    def test_deepseek_provider_in_inventory(self) -> None:
        with self._patches():
            item = upsert_secret(
                "provider:deepseek",
                value="sk-ds-test-key",
                updated_by="admin-1",
            )
            keys = [entry["key"] for entry in list_secrets_metadata()]
        self.assertIn("provider:deepseek", keys)
        self.assertEqual(item["label"], "DeepSeek")
        self.assertTrue(item["configured"])

    def test_delete_secret_removes_metadata(self) -> None:
        with self._patches():
            upsert_secret("linear.token", value="lin_test", label="Linear")
            self.assertTrue(delete_secret("linear.token"))
            items = list_secrets_metadata()
        self.assertFalse(any(item["key"] == "linear.token" for item in items))

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "resolve_pg_tenant_id", return_value="acme")
    @patch.object(admin_routes, "get_current_sub", return_value="admin-1")
    @patch.object(admin_routes, "_audit_secret")
    @patch.object(admin_routes, "upsert_secret")
    def test_admin_secrets_upsert_audited(self, mock_upsert: MagicMock, mock_audit: MagicMock, *_m: object) -> None:
        mock_upsert.return_value = {
            "key": "siem.webhook",
            "category": "webhook",
            "label": "SIEM",
            "configured": True,
        }
        body = admin_routes.SecretUpsertBody(value="whsec_test", label="SIEM", category="webhook")
        out = admin_routes.admin_secrets_upsert("siem.webhook", body)
        self.assertTrue(out["ok"])
        mock_audit.assert_called_once()

    @patch.object(admin_routes, "require_any_role")
    @patch.object(admin_routes, "test_provider_connection", return_value={"ok": True, "message": "connection_ok"})
    def test_admin_inference_provider_test_shape(self, mock_test: MagicMock, *_m: object) -> None:
        out = admin_routes.admin_inference_provider_test("openrouter")
        self.assertTrue(out["ok"])
        mock_test.assert_called_once_with("openrouter")


if __name__ == "__main__":
    unittest.main()
