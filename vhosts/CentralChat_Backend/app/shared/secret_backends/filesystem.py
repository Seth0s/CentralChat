"""Filesystem encrypted backend (default, Phase 1)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.shared.encrypted_vault import (
    load_provider_secrets_map,
    read_secret_doc,
    save_provider_secrets_map,
    write_secret_doc,
)
from app.shared.secret_backends.keys import (
    custom_value_filename,
    is_provider_key,
    normalize_logical_key,
    provider_id_from_key,
)

logger = logging.getLogger(__name__)

PROVIDER_SECRETS_FILENAME = "inference_providers.json"


class FilesystemEncryptedBackend:
    backend_id = "filesystem"

    def __init__(self, root: str | None = None) -> None:
        self._root_override = root

    def _root(self) -> Path:
        if self._root_override:
            return Path(self._root_override)
        from app.config import CENTRAL_ROOT

        return Path((CENTRAL_ROOT or "/tmp/central").strip() or "/tmp/central")

    def _secrets_dir(self) -> Path:
        return self._root() / "secrets"

    def _provider_secrets_path(self) -> Path:
        return self._secrets_dir() / PROVIDER_SECRETS_FILENAME

    def _custom_value_path(self, logical_key: str) -> Path:
        return self._secrets_dir() / "values" / f"{custom_value_filename(logical_key)}.json"

    def is_available(self) -> bool:
        return True

    def read(self, logical_key: str) -> str:
        key = normalize_logical_key(logical_key)
        if not key:
            return ""
        if is_provider_key(key):
            pid = provider_id_from_key(key)
            return load_provider_secrets_map(self._provider_secrets_path()).get(pid, "")
        return read_secret_doc(self._custom_value_path(key))

    def write(self, logical_key: str, value: str) -> None:
        key = normalize_logical_key(logical_key)
        stripped = (value or "").strip()
        if not key:
            raise ValueError("invalid_secret_key")
        if is_provider_key(key):
            pid = provider_id_from_key(key)
            secrets = load_provider_secrets_map(self._provider_secrets_path())
            if stripped:
                secrets[pid] = stripped
            elif pid in secrets:
                del secrets[pid]
            save_provider_secrets_map(self._provider_secrets_path(), secrets)
            return
        write_secret_doc(self._custom_value_path(key), stripped)

    def delete(self, logical_key: str) -> None:
        key = normalize_logical_key(logical_key)
        if not key:
            return
        if is_provider_key(key):
            pid = provider_id_from_key(key)
            secrets = load_provider_secrets_map(self._provider_secrets_path())
            if pid in secrets:
                del secrets[pid]
                save_provider_secrets_map(self._provider_secrets_path(), secrets)
            return
        path = self._custom_value_path(key)
        if path.is_file():
            path.unlink()

    def describe(self) -> dict[str, str]:
        enc = "yes" if __import__("app.shared.encrypted_vault", fromlist=["encryption_enabled"]).encryption_enabled() else "no"
        return {
            "backend": self.backend_id,
            "root": str(self._root()),
            "encryption_enabled": enc,
        }

    def load_all_provider_secrets(self) -> dict[str, str]:
        return load_provider_secrets_map(self._provider_secrets_path())

    def save_all_provider_secrets(self, secrets: dict[str, str]) -> None:
        save_provider_secrets_map(self._provider_secrets_path(), secrets)
