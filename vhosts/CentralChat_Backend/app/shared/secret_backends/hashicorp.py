"""HashiCorp Vault KV v2 backend (httpx, no hvac dependency)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import (
    CENTRAL_HASHICORP_VAULT_ADDR,
    CENTRAL_HASHICORP_VAULT_MOUNT,
    CENTRAL_HASHICORP_VAULT_NAMESPACE,
    CENTRAL_HASHICORP_VAULT_PREFIX,
    CENTRAL_HASHICORP_VAULT_TOKEN,
)
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.secret_backends.keys import normalize_logical_key, storage_segment

logger = logging.getLogger(__name__)


class HashicorpVaultBackend:
    backend_id = "hashicorp"

    def __init__(
        self,
        *,
        addr: str | None = None,
        token: str | None = None,
        mount: str | None = None,
        prefix: str | None = None,
        namespace: str | None = None,
        tenant_scoped: bool = True,
    ) -> None:
        self._addr = (addr or CENTRAL_HASHICORP_VAULT_ADDR).strip().rstrip("/")
        self._token = (token or CENTRAL_HASHICORP_VAULT_TOKEN).strip()
        self._mount = (mount or CENTRAL_HASHICORP_VAULT_MOUNT).strip().strip("/") or "secret"
        self._prefix = (prefix or CENTRAL_HASHICORP_VAULT_PREFIX).strip().strip("/")
        self._namespace = (namespace or CENTRAL_HASHICORP_VAULT_NAMESPACE).strip()
        self._tenant_scoped = tenant_scoped

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["X-Vault-Token"] = self._token
        if self._namespace:
            headers["X-Vault-Namespace"] = self._namespace
        return headers

    def _vault_path(self, logical_key: str) -> str:
        key = storage_segment(logical_key)
        parts = [p for p in (self._prefix, resolve_pg_tenant_id() if self._tenant_scoped else "", key) if p]
        return "/".join(parts)

    def _data_url(self, logical_key: str) -> str:
        path = quote(self._vault_path(logical_key), safe="/")
        return f"{self._addr}/v1/{self._mount}/data/{path}"

    def _metadata_url(self, logical_key: str) -> str:
        path = quote(self._vault_path(logical_key), safe="/")
        return f"{self._addr}/v1/{self._mount}/metadata/{path}"

    def is_available(self) -> bool:
        if not self._addr or not self._token:
            return False
        try:
            resp = httpx.get(f"{self._addr}/v1/sys/health", headers=self._headers(), timeout=4.0)
            return resp.status_code in (200, 429, 472, 473)
        except Exception:
            logger.debug("hashicorp vault health check failed", exc_info=True)
            return False

    def read(self, logical_key: str) -> str:
        key = normalize_logical_key(logical_key)
        if not key or not self._addr or not self._token:
            return ""
        try:
            resp = httpx.get(self._data_url(key), headers=self._headers(), timeout=8.0)
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
            data = payload.get("data", {}).get("data", {})
            if isinstance(data, dict):
                return str(data.get("value") or "").strip()
        except Exception:
            logger.debug("hashicorp vault read failed key=%s", key, exc_info=True)
        return ""

    def write(self, logical_key: str, value: str) -> None:
        key = normalize_logical_key(logical_key)
        stripped = (value or "").strip()
        if not key:
            raise ValueError("invalid_secret_key")
        if not self._addr or not self._token:
            raise RuntimeError("hashicorp_vault_not_configured")
        if not stripped:
            self.delete(key)
            return
        body = json.dumps({"data": {"value": stripped}})
        resp = httpx.post(
            self._data_url(key),
            content=body,
            headers=self._headers(),
            timeout=8.0,
        )
        resp.raise_for_status()

    def delete(self, logical_key: str) -> None:
        key = normalize_logical_key(logical_key)
        if not key or not self._addr or not self._token:
            return
        try:
            resp = httpx.delete(self._metadata_url(key), headers=self._headers(), timeout=8.0)
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
        except Exception:
            logger.debug("hashicorp vault delete failed key=%s", key, exc_info=True)

    def describe(self) -> dict[str, str]:
        return {
            "backend": self.backend_id,
            "addr": self._addr or "",
            "mount": self._mount,
            "prefix": self._prefix,
            "tenant_scoped": "yes" if self._tenant_scoped else "no",
        }
