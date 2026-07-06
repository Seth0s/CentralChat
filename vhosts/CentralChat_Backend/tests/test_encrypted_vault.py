"""Tests for encrypted_vault (AES-256-GCM at rest)."""

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.shared.encrypted_vault import (
    decrypt_value,
    encrypt_value,
    encryption_enabled,
    is_encrypted_envelope,
    load_provider_secrets_map,
    migrate_plaintext_at_rest,
    read_secret_doc,
    save_provider_secrets_map,
    write_secret_doc,
)

_TEST_KEY = base64.b64encode(b"x" * 32).decode("ascii")


class EncryptedVaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "values").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_encrypt_decrypt_roundtrip(self) -> None:
        with patch.dict(os.environ, {"CENTRAL_VAULT_MASTER_KEY": _TEST_KEY}):
            envelope = encrypt_value("sk-secret-value")
            self.assertTrue(is_encrypted_envelope(envelope))
            self.assertEqual(decrypt_value(envelope), "sk-secret-value")

    def test_plaintext_when_no_master_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CENTRAL_VAULT_MASTER_KEY", None)
            path = self.root / "values" / "custom.json"
            write_secret_doc(path, "plain-value")
            self.assertEqual(read_secret_doc(path), "plain-value")
            raw = path.read_text(encoding="utf-8")
            self.assertIn("plain-value", raw)

    def test_encrypted_custom_secret_on_disk(self) -> None:
        with patch.dict(os.environ, {"CENTRAL_VAULT_MASTER_KEY": _TEST_KEY}):
            path = self.root / "values" / "siem.webhook.json"
            write_secret_doc(path, "whsec_super_secret")
            self.assertEqual(read_secret_doc(path), "whsec_super_secret")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("whsec_super_secret", raw)
            self.assertIn('"v": 1', raw)

    def test_provider_secrets_encrypted(self) -> None:
        with patch.dict(os.environ, {"CENTRAL_VAULT_MASTER_KEY": _TEST_KEY}):
            path = self.root / "inference_providers.json"
            save_provider_secrets_map(path, {"deepseek": "sk-ds-test"})
            loaded = load_provider_secrets_map(path)
            self.assertEqual(loaded["deepseek"], "sk-ds-test")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("sk-ds-test", raw)

    def test_migrate_plaintext_at_rest(self) -> None:
        path = self.root / "inference_providers.json"
        path.write_text('{"anthropic": "sk-ant-plain"}', encoding="utf-8")
        with patch.dict(os.environ, {"CENTRAL_VAULT_MASTER_KEY": _TEST_KEY}):
            count = migrate_plaintext_at_rest(self.root)
            self.assertGreaterEqual(count, 1)
            self.assertNotIn("sk-ant-plain", path.read_text(encoding="utf-8"))
            self.assertEqual(load_provider_secrets_map(path)["anthropic"], "sk-ant-plain")

    def test_encryption_disabled_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CENTRAL_VAULT_MASTER_KEY", None)
            self.assertFalse(encryption_enabled())


if __name__ == "__main__":
    unittest.main()
