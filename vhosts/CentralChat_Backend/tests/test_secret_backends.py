"""Tests for Phase 3 secret backends."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.shared.secret_backends import (
    get_secret_backend,
    load_provider_secrets_from_backend,
    migrate_filesystem_secrets_to_backend,
    read_secret_value,
    reset_secret_backend_cache,
    write_secret_value,
)
from app.shared.secret_backends.base import SecretBackendReadOnlyError
from app.shared.secret_backends.env_backend import EnvOnlyBackend
from app.shared.secret_backends.filesystem import FilesystemEncryptedBackend
from app.shared.secret_backends.hashicorp import HashicorpVaultBackend


class SecretBackendsTest(unittest.TestCase):
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

    def test_filesystem_roundtrip(self) -> None:
        backend = FilesystemEncryptedBackend(str(self.root))
        backend.write("siem.webhook", "https://siem.example/hook")
        backend.write("provider:deepseek", "sk-ds-test")
        self.assertEqual(backend.read("siem.webhook"), "https://siem.example/hook")
        self.assertEqual(backend.read("provider:deepseek"), "sk-ds-test")
        backend.delete("siem.webhook")
        self.assertEqual(backend.read("siem.webhook"), "")

    def test_env_backend_read_only(self) -> None:
        backend = EnvOnlyBackend()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}):
            self.assertEqual(backend.read("provider:deepseek"), "sk-env")
        with self.assertRaises(SecretBackendReadOnlyError):
            backend.write("provider:deepseek", "x")

    @patch.dict(os.environ, {"CENTRAL_SECRET_BACKEND": "filesystem"}, clear=False)
    @patch("app.shared.secret_backends.CENTRAL_SECRET_BACKEND", "filesystem")
    def test_factory_filesystem_default(self) -> None:
        reset_secret_backend_cache()
        with patch("app.config.CENTRAL_ROOT", str(self.root)):
            with patch("app.shared.inference_governance.CENTRAL_ROOT", str(self.root)):
                write_secret_value("alert.webhook", "https://alert.example")
                self.assertEqual(read_secret_value("alert.webhook"), "https://alert.example")
        self.assertEqual(get_secret_backend().backend_id, "filesystem")

    @patch("app.shared.secret_backends.hashicorp.httpx.get")
    def test_hashicorp_read(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"data": {"value": "sk-vault"}}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        backend = HashicorpVaultBackend(
            addr="http://127.0.0.1:8200",
            token="test-token",
            prefix="centralchat",
            tenant_scoped=False,
        )
        self.assertEqual(backend.read("provider:openrouter"), "sk-vault")

    @patch("app.shared.secret_backends.hashicorp.httpx.post")
    def test_hashicorp_write(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        backend = HashicorpVaultBackend(
            addr="http://127.0.0.1:8200",
            token="test-token",
            tenant_scoped=False,
        )
        backend.write("siem.webhook", "https://siem.example")
        self.assertTrue(mock_post.called)

    @patch.dict(os.environ, {"CENTRAL_SECRET_BACKEND": "hashicorp"}, clear=False)
    @patch("app.shared.secret_backends.CENTRAL_SECRET_BACKEND", "hashicorp")
    def test_migrate_filesystem_to_hashicorp(self) -> None:
        reset_secret_backend_cache()
        fs = FilesystemEncryptedBackend(str(self.root))
        fs.write("provider:anthropic", "sk-ant-migrate")
        fs.write("quota.webhook", "https://quota.example")

        class _FakeHashicorp:
            backend_id = "hashicorp"

            def read(self, key: str) -> str:
                return self._store.get(key, "")

            def write(self, key: str, value: str) -> None:
                self._store[key] = value

            def delete(self, key: str) -> None:
                self._store.pop(key, None)

            def is_available(self) -> bool:
                return True

            def describe(self) -> dict[str, str]:
                return {"backend": "hashicorp"}

            def __init__(self) -> None:
                self._store: dict[str, str] = {}

        fake = _FakeHashicorp()
        with patch("app.shared.secret_backends.get_secret_backend", return_value=fake):
            with patch("app.config.CENTRAL_ROOT", str(self.root)):
                count = migrate_filesystem_secrets_to_backend()
        self.assertEqual(count, 2)
        self.assertEqual(fake.read("provider:anthropic"), "sk-ant-migrate")

    def test_load_provider_secrets_from_backend(self) -> None:
        fs = FilesystemEncryptedBackend(str(self.root))
        fs.write("provider:openai", "sk-openai")
        reset_secret_backend_cache()
        with patch.dict(os.environ, {"CENTRAL_SECRET_BACKEND": "filesystem"}, clear=False):
            with patch("app.shared.secret_backends.CENTRAL_SECRET_BACKEND", "filesystem"):
                with patch("app.config.CENTRAL_ROOT", str(self.root)):
                    secrets = load_provider_secrets_from_backend()
        self.assertEqual(secrets.get("openai"), "sk-openai")


if __name__ == "__main__":
    unittest.main()
