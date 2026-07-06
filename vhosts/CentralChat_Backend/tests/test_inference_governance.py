"""Tests for inference governance (G1–G2)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.shared.inference_governance import (
    KNOWN_PROVIDERS,
    check_model_allowed,
    configure_provider,
    filter_vendor_catalog,
    get_global_models_allowlist,
    is_provider_configured,
    merge_user_cloud_models,
    model_supported_by_providers,
    set_global_models_allowlist,
    validate_tenant_models_allowlist,
    validate_user_cloud_models_payload,
)
from app.shared.secret_backends import reset_secret_backend_cache


VENDOR = [
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini"},
    {"id": "anthropic/claude-3.5-sonnet", "label": "Claude 3.5"},
    {"id": "google/gemini-2.0-flash", "label": "Gemini Flash"},
    {"id": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
]


class InferenceGovernanceTest(unittest.TestCase):
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
        stack.enter_context(patch("app.shared.inference_governance.CENTRAL_ROOT", str(self.root)))
        stack.enter_context(patch("app.config.CENTRAL_ROOT", str(self.root)))
        stack.enter_context(patch("app.shared.inference_governance.OPENROUTER_API_KEY", "test-key"))
        stack.enter_context(patch("app.shared.inference_governance.CENTRAL_CLOUD_MODEL_ALLOWLIST", ()))
        return stack

    def test_global_allowlist_filters_vendor(self) -> None:
        with self._patches():
            set_global_models_allowlist(["openai/gpt-4o-mini"])
            filtered = filter_vendor_catalog(VENDOR, tenant_id="default")
        self.assertEqual([r["id"] for r in filtered], ["openai/gpt-4o-mini"])

    def test_tenant_subset_of_global_rejected(self) -> None:
        with self._patches():
            set_global_models_allowlist(["openai/gpt-4o-mini"])
            with self.assertRaises(ValueError):
                validate_tenant_models_allowlist(["anthropic/claude-3.5-sonnet"])

    def test_user_put_rejects_unknown_model(self) -> None:
        with self._patches():
            set_global_models_allowlist(["openai/gpt-4o-mini"])
            allowed = frozenset(["openai/gpt-4o-mini"])
            with self.assertRaises(ValueError) as ctx:
                validate_user_cloud_models_payload(
                    [{"id": "anthropic/claude-3.5-sonnet", "enabled": True}],
                    allowed,
                )
            self.assertEqual(str(ctx.exception), "model_not_in_tenant_catalog")

    def test_check_model_denied_outside_global(self) -> None:
        with self._patches():
            set_global_models_allowlist(["openai/gpt-4o-mini"])
            result = check_model_allowed("anthropic/claude-3.5-sonnet")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "policy_model_denied")

    def test_merge_defaults_enabled_true(self) -> None:
        with self._patches():
            merged = merge_user_cloud_models(VENDOR[:1], {})
        self.assertTrue(merged[0]["enabled"])

    def test_provider_configure_without_exposing_key(self) -> None:
        with self._patches():
            item = configure_provider("anthropic", api_key="sk-ant-test", enabled=True)
        self.assertEqual(item["id"], "anthropic")
        self.assertTrue(item["configured"])
        secrets_path = self.root / "secrets" / "inference_providers.json"
        self.assertTrue(secrets_path.is_file())

    def test_deepseek_provider_governance(self) -> None:
        self.assertIn("deepseek", KNOWN_PROVIDERS)
        with self._patches():
            with patch("app.shared.inference_governance.OPENROUTER_API_KEY", ""):
                configure_provider("deepseek", api_key="sk-ds-test", enabled=True)
                self.assertTrue(is_provider_configured("deepseek"))
                self.assertTrue(model_supported_by_providers("deepseek/deepseek-v4-pro"))
                filtered = filter_vendor_catalog(
                    [v for v in VENDOR if v["id"].startswith("deepseek/")],
                    tenant_id="default",
                )
        self.assertEqual(len(filtered), 1)

    def test_env_global_allowlist_union(self) -> None:
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(patch("app.shared.inference_governance.CENTRAL_ROOT", str(self.root)))
            stack.enter_context(patch("app.shared.inference_governance.OPENROUTER_API_KEY", "k"))
            stack.enter_context(
                patch("app.shared.inference_governance.CENTRAL_CLOUD_MODEL_ALLOWLIST", ("openai/gpt-4o-mini",))
            )
            set_global_models_allowlist(["anthropic/claude-3.5-sonnet"])
            al = get_global_models_allowlist()
        self.assertIsNotNone(al)
        assert al is not None
        self.assertIn("openai/gpt-4o-mini", al)
        self.assertIn("anthropic/claude-3.5-sonnet", al)


if __name__ == "__main__":
    unittest.main()
