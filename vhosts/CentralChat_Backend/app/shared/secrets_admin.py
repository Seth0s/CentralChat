"""Admin secrets — metadata only in API responses; values stay on disk."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import CENTRAL_ROOT
from app.shared.inference_governance import (
    KNOWN_PROVIDERS,
    configure_provider,
    is_provider_configured,
    list_providers_public,
    save_provider_secret,
    _provider_api_key,
)
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.secret_refs_store import (
    delete_secret_ref,
    list_secret_ref_enrichment,
    sync_secret_metadata_from_item,
    upsert_inference_provider_status,
)
from app.shared.integration_secret_keys import KNOWN_INTEGRATION_SECRETS
from app.shared.secret_backends import (
    delete_secret_value,
    read_secret_value,
    secret_backend_info,
    write_secret_value,
)
from app.shared.secret_backends.base import SecretBackendReadOnlyError

logger = logging.getLogger(__name__)

SECRET_KEY_RE = re.compile(r"^[a-z][a-z0-9._:-]{1,120}$")
INDEX_FILENAME = "secrets_index.json"
VALUES_DIRNAME = "values"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path((CENTRAL_ROOT or "/tmp/central").strip() or "/tmp/central")


def _secrets_dir() -> Path:
    return _root() / "secrets"


def _index_path() -> Path:
    return _secrets_dir() / INDEX_FILENAME


def _values_dir() -> Path:
    return _secrets_dir() / VALUES_DIRNAME


def _safe_value_path(key: str) -> Path:
    safe = key.replace(":", "__")
    return _values_dir() / f"{safe}.json"


def _key_prefix(value: str) -> str:
    stripped = (value or "").strip()
    if len(stripped) <= 4:
        return "****"
    return f"{stripped[:4]}…"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("secrets_admin: read failed %s", path, exc_info=True)
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_index() -> dict[str, Any]:
    return _read_json(_index_path())


def _save_index(data: dict[str, Any]) -> None:
    _write_json(_index_path(), data)


def _provider_secret_key(provider_id: str) -> str:
    return f"provider:{provider_id.strip().lower()}"


def _is_provider_secret(key: str) -> bool:
    return key.startswith("provider:")


def _provider_id_from_key(key: str) -> str:
    return key.split(":", 1)[1].strip().lower()


def _provider_metadata_entries() -> list[dict[str, Any]]:
    index = _load_index()
    items: list[dict[str, Any]] = []
    for provider in list_providers_public():
        pid = str(provider["id"])
        key = _provider_secret_key(pid)
        configured = bool(provider.get("configured"))
        api_key = _provider_api_key(pid) if configured else ""
        meta = index.get(key) if isinstance(index.get(key), dict) else {}
        items.append(
            {
                "key": key,
                "category": "provider",
                "label": str(provider.get("label") or pid),
                "configured": configured,
                "enabled": bool(provider.get("enabled", True)),
                "source": str(provider.get("source") or "none"),
                "prefix": _key_prefix(api_key) if configured else None,
                "updated_at": meta.get("updated_at"),
                "updated_by": meta.get("updated_by"),
                "last_used_at": meta.get("last_used_at"),
            }
        )
    return items


def _custom_metadata_entries() -> list[dict[str, Any]]:
    index = _load_index()
    items: list[dict[str, Any]] = []
    for key, raw in index.items():
        if not isinstance(raw, dict) or _is_provider_secret(str(key)):
            continue
        value = read_secret_value(str(key))
        items.append(
            {
                "key": str(key),
                "category": str(raw.get("category") or "custom"),
                "label": str(raw.get("label") or key),
                "configured": bool(value),
                "enabled": raw.get("enabled", True) is not False,
                "source": "vault",
                "prefix": _key_prefix(value) if value else None,
                "updated_at": raw.get("updated_at"),
                "updated_by": raw.get("updated_by"),
                "last_used_at": raw.get("last_used_at"),
            }
        )
    return sorted(items, key=lambda item: item["key"])


def list_secrets_metadata(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    providers = _provider_metadata_entries()
    customs = _custom_metadata_entries()
    items = sorted(providers + customs, key=lambda item: (item["category"], item["key"]))
    enrichment = list_secret_ref_enrichment(tenant_id=tenant_id)
    if not enrichment:
        return items
    merged: list[dict[str, Any]] = []
    for item in items:
        entry = dict(item)
        extra = enrichment.get(str(entry["key"]))
        if extra:
            if extra.get("last_test_at"):
                entry["last_test_at"] = extra["last_test_at"]
            if extra.get("last_test_ok") is not None:
                entry["last_test_ok"] = extra["last_test_ok"]
            if extra.get("last_test_message"):
                entry["last_test_message"] = extra["last_test_message"]
            if extra.get("active_version_count") is not None:
                entry["active_version_count"] = extra["active_version_count"]
            if extra.get("value_fingerprint"):
                entry["value_fingerprint"] = extra["value_fingerprint"]
        merged.append(entry)
    return merged


def get_secret_metadata(key: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    normalized = (key or "").strip().lower()
    for item in list_secrets_metadata(tenant_id=tenant_id):
        if item["key"] == normalized:
            return item
    return None


def upsert_secret(
    key: str,
    *,
    value: str,
    label: str | None = None,
    category: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    normalized = (key or "").strip().lower()
    if not SECRET_KEY_RE.fullmatch(normalized):
        raise ValueError("invalid_secret_key")
    if not (value or "").strip():
        raise ValueError("empty_secret_value")

    if _is_provider_secret(normalized):
        pid = _provider_id_from_key(normalized)
        if pid not in KNOWN_PROVIDERS:
            raise ValueError("provider_unknown")
        try:
            configure_provider(pid, api_key=value.strip(), enabled=True)
        except SecretBackendReadOnlyError as exc:
            raise ValueError("secret_backend_read_only") from exc
    else:
        try:
            write_secret_value(normalized, value.strip())
        except SecretBackendReadOnlyError as exc:
            raise ValueError("secret_backend_read_only") from exc

    index = _load_index()
    entry = dict(index.get(normalized) or {}) if isinstance(index.get(normalized), dict) else {}
    if label:
        entry["label"] = label.strip()
    if category:
        entry["category"] = category.strip()
    entry["updated_at"] = _utc_now_iso()
    if updated_by:
        entry["updated_by"] = updated_by
    index[normalized] = entry
    _save_index(index)
    meta = get_secret_metadata(normalized)
    if not meta:
        raise RuntimeError("secret_metadata_missing")
    tid = resolve_pg_tenant_id()
    api_key_for_pg = value.strip() if _is_provider_secret(normalized) else value.strip()
    try:
        sync_secret_metadata_from_item(
            meta,
            tenant_id=tid,
            updated_by=updated_by,
            api_key=api_key_for_pg if meta.get("configured") else None,
        )
    except Exception:
        logger.debug("secrets_admin: pg sync failed key=%s", normalized, exc_info=True)
    return meta


def delete_secret(key: str) -> bool:
    normalized = (key or "").strip().lower()
    if not normalized:
        raise ValueError("invalid_secret_key")

    if _is_provider_secret(normalized):
        pid = _provider_id_from_key(normalized)
        if pid not in KNOWN_PROVIDERS:
            raise ValueError("provider_unknown")
        save_provider_secret(pid, "")
        configure_provider(pid, enabled=False)
        upsert_inference_provider_status(
            tenant_id=resolve_pg_tenant_id(),
            provider_id=pid,
            configured=False,
        )
    else:
        try:
            delete_secret_value(normalized)
        except SecretBackendReadOnlyError as exc:
            raise ValueError("secret_backend_read_only") from exc

    index = _load_index()
    if normalized not in index:
        return False
    del index[normalized]
    _save_index(index)
    try:
        delete_secret_ref(tenant_id=resolve_pg_tenant_id(), secret_key=normalized)
    except Exception:
        logger.debug("secrets_admin: pg delete failed key=%s", normalized, exc_info=True)
    return True


def test_provider_connection(provider_id: str) -> dict[str, Any]:
    pid = (provider_id or "").strip().lower()
    if pid not in KNOWN_PROVIDERS:
        raise ValueError("provider_unknown")
    if not is_provider_configured(pid):
        return {"ok": False, "message": "provider_not_configured"}

    api_key = _provider_api_key(pid)
    if not api_key:
        return {"ok": False, "message": "provider_not_configured"}

    if pid == "openrouter":
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
    elif pid == "openai":
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
    elif pid == "anthropic":
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="GET",
        )
    elif pid == "google":
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            method="GET",
        )
    elif pid == "deepseek":
        req = urllib.request.Request(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
    else:
        result = {"ok": True, "message": "provider_configured"}

    if "result" not in locals():
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                ok = 200 <= response.status < 300
                result = {"ok": ok, "message": "connection_ok" if ok else f"http_{response.status}"}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                result = {"ok": False, "message": "invalid_credentials"}
            else:
                result = {"ok": False, "message": f"http_{exc.code}"}
        except Exception:
            logger.debug("provider test failed for %s", pid, exc_info=True)
            result = {"ok": False, "message": "connection_failed"}

    try:
        upsert_inference_provider_status(
            tenant_id=resolve_pg_tenant_id(),
            provider_id=pid,
            configured=True,
            last_test_ok=bool(result.get("ok")),
            last_test_message=str(result.get("message") or ""),
        )
    except Exception:
        logger.debug("secrets_admin: provider status pg sync failed", exc_info=True)
    return result


def test_secret(key: str) -> dict[str, Any]:
    normalized = (key or "").strip().lower()
    if _is_provider_secret(normalized):
        return test_provider_connection(_provider_id_from_key(normalized))

    meta = get_secret_metadata(normalized)
    if not meta:
        raise ValueError("secret_not_found")
    if not meta.get("configured"):
        return {"ok": False, "message": "secret_not_configured"}
    return {"ok": True, "message": "secret_present"}


def read_custom_secret(key: str) -> str:
    """Runtime resolver for custom secrets (not providers)."""
    normalized = (key or "").strip().lower()
    if not SECRET_KEY_RE.fullmatch(normalized) or _is_provider_secret(normalized):
        return ""
    return read_secret_value(normalized)


def secrets_storage_info() -> dict[str, object]:
    return secret_backend_info()


def list_known_integration_secret_keys() -> list[dict[str, str]]:
    return [
        {"key": key, **{k: str(v) for k, v in meta.items() if k != "description"}}
        for key, meta in sorted(KNOWN_INTEGRATION_SECRETS.items())
    ]
