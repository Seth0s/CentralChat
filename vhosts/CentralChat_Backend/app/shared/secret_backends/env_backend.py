"""Env-only backend — runtime reads from environment; writes are disabled."""

from __future__ import annotations

import os

from app.config import (
    CENTRAL_ALERT_WEBHOOK_URL,
    CENTRAL_QUOTA_WEBHOOK_URL,
    CENTRAL_SIEM_HEC_TOKEN,
)
from app.shared.secret_backends.base import SecretBackendReadOnlyError
from app.shared.secret_backends.keys import (
    is_provider_key,
    normalize_logical_key,
    provider_id_from_key,
)

_CUSTOM_ENV_KEYS: dict[str, str] = {
    "siem.hec_token": "CENTRAL_SIEM_HEC_TOKEN",
    "alert.webhook": "CENTRAL_ALERT_WEBHOOK_URL",
    "quota.webhook": "CENTRAL_QUOTA_WEBHOOK_URL",
}


class EnvOnlyBackend:
    backend_id = "env"

    def is_available(self) -> bool:
        return True

    def read(self, logical_key: str) -> str:
        key = normalize_logical_key(logical_key)
        if not key:
            return ""
        if is_provider_key(key):
            pid = provider_id_from_key(key)
            from app.shared.inference_governance import KNOWN_PROVIDERS

            meta = KNOWN_PROVIDERS.get(pid) or {}
            env_key = str(meta.get("env_key") or "")
            return os.getenv(env_key, "").strip() if env_key else ""
        env_name = _CUSTOM_ENV_KEYS.get(key)
        if env_name:
            return os.getenv(env_name, "").strip()
        return ""

    def write(self, logical_key: str, value: str) -> None:
        raise SecretBackendReadOnlyError("env_backend_is_read_only")

    def delete(self, logical_key: str) -> None:
        raise SecretBackendReadOnlyError("env_backend_is_read_only")

    def describe(self) -> dict[str, str]:
        return {"backend": self.backend_id, "mode": "read_only"}
