"""Secret backend factory and filesystem migration (Phase 3)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config import CENTRAL_SECRET_BACKEND
from app.shared.secret_backends.aws import AwsSecretsManagerBackend
from app.shared.secret_backends.base import SecretBackend, SecretBackendReadOnlyError
from app.shared.secret_backends.env_backend import EnvOnlyBackend
from app.shared.secret_backends.filesystem import FilesystemEncryptedBackend
from app.shared.secret_backends.hashicorp import HashicorpVaultBackend
from app.shared.secret_backends.keys import provider_logical_key

logger = logging.getLogger(__name__)

_MIGRATED_TO_EXTERNAL = False


def _normalize_backend_id(raw: str | None) -> str:
    value = (raw or CENTRAL_SECRET_BACKEND or "filesystem").strip().lower()
    aliases = {
        "file": "filesystem",
        "filesystem_encrypted": "filesystem",
        "hashicorp_vault": "hashicorp",
        "vault": "hashicorp",
        "aws_secrets_manager": "aws",
        "secretsmanager": "aws",
    }
    return aliases.get(value, value)


@lru_cache(maxsize=1)
def get_secret_backend() -> SecretBackend:
    backend_id = _normalize_backend_id(CENTRAL_SECRET_BACKEND)
    if backend_id == "env":
        return EnvOnlyBackend()
    if backend_id == "hashicorp":
        return HashicorpVaultBackend()
    if backend_id == "aws":
        return AwsSecretsManagerBackend()
    return FilesystemEncryptedBackend()


def secret_backend_info() -> dict[str, Any]:
    backend = get_secret_backend()
    info: dict[str, Any] = {
        "backend_id": backend.backend_id,
        "configured_backend": _normalize_backend_id(CENTRAL_SECRET_BACKEND),
        **backend.describe(),
    }
    try:
        info["available"] = backend.is_available()
    except Exception:
        info["available"] = False
    info["read_only"] = backend.backend_id == "env"
    return info


def read_secret_value(logical_key: str) -> str:
    return get_secret_backend().read(logical_key)


def write_secret_value(logical_key: str, value: str) -> None:
    get_secret_backend().write(logical_key, value)


def delete_secret_value(logical_key: str) -> None:
    get_secret_backend().delete(logical_key)


def load_provider_secrets_from_backend() -> dict[str, str]:
    backend = get_secret_backend()
    if backend.backend_id == "filesystem":
        fs = FilesystemEncryptedBackend()
        return fs.load_all_provider_secrets()
    out: dict[str, str] = {}
    from app.shared.inference_governance import KNOWN_PROVIDERS

    for pid in KNOWN_PROVIDERS:
        val = backend.read(provider_logical_key(pid))
        if val:
            out[pid] = val
    return out


def save_provider_secret_to_backend(provider_id: str, api_key: str) -> None:
    pid = (provider_id or "").strip().lower()
    key = provider_logical_key(pid)
    stripped = (api_key or "").strip()
    backend = get_secret_backend()
    if not stripped:
        backend.delete(key)
        return
    backend.write(key, stripped)


def migrate_filesystem_secrets_to_backend() -> int:
    """One-shot copy from filesystem vault to external backend."""
    global _MIGRATED_TO_EXTERNAL
    if _MIGRATED_TO_EXTERNAL:
        return 0
    _MIGRATED_TO_EXTERNAL = True

    backend = get_secret_backend()
    if backend.backend_id == "filesystem":
        return 0
    if backend.backend_id == "env":
        return 0

    fs = FilesystemEncryptedBackend()
    migrated = 0

    for pid, value in fs.load_all_provider_secrets().items():
        logical = provider_logical_key(pid)
        if backend.read(logical):
            continue
        try:
            backend.write(logical, value)
            migrated += 1
        except Exception:
            logger.debug("migrate provider secret failed pid=%s", pid, exc_info=True)

    values_dir = fs._secrets_dir() / "values"
    if values_dir.is_dir():
        from app.shared.encrypted_vault import read_secret_doc

        for path in values_dir.glob("*.json"):
            logical = path.stem.replace("__", ":")
            if backend.read(logical):
                continue
            value = read_secret_doc(path)
            if not value:
                continue
            try:
                backend.write(logical, value)
                migrated += 1
            except Exception:
                logger.debug("migrate custom secret failed key=%s", logical, exc_info=True)

    if migrated:
        logger.info("secret_backend: migrated %s secrets from filesystem to %s", migrated, backend.backend_id)
    return migrated


def reset_secret_backend_cache() -> None:
    """Test helper — clear cached backend and migration flags."""
    global _MIGRATED_TO_EXTERNAL
    get_secret_backend.cache_clear()
    _MIGRATED_TO_EXTERNAL = False


__all__ = [
    "SecretBackend",
    "SecretBackendReadOnlyError",
    "delete_secret_value",
    "get_secret_backend",
    "load_provider_secrets_from_backend",
    "migrate_filesystem_secrets_to_backend",
    "read_secret_value",
    "reset_secret_backend_cache",
    "save_provider_secret_to_backend",
    "secret_backend_info",
    "write_secret_value",
]
