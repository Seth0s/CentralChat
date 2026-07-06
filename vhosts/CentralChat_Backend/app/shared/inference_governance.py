"""Inference governance — provider keys, global/tenant allowlists, effective catalog."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import CENTRAL_CLOUD_MODEL_ALLOWLIST, CENTRAL_ROOT, OPENROUTER_API_KEY
from app.shared.encrypted_vault import migrate_plaintext_at_rest
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.policy_engine import _load_tenant_policies
from app.shared.secret_backends import (
    load_provider_secrets_from_backend,
    migrate_filesystem_secrets_to_backend,
    save_provider_secret_to_backend,
    secret_backend_info,
)

logger = logging.getLogger(__name__)

GOVERNANCE_FILENAME = "inference_governance.json"
PROVIDER_SECRETS_FILENAME = "inference_providers.json"

# Provider registry: env bootstrap + optional admin-managed secrets file.
KNOWN_PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "covers_all": True,
    },
    "anthropic": {
        "label": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "prefixes": ("anthropic/",),
    },
    "openai": {
        "label": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "prefixes": ("openai/",),
    },
    "google": {
        "label": "Google",
        "env_key": "GOOGLE_API_KEY",
        "prefixes": ("google/",),
    },
    "deepseek": {
        "label": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "prefixes": ("deepseek/",),
    },
}


@dataclass
class ModelAllowResult:
    allowed: bool
    code: str | None = None
    message_pt: str | None = None


def _root() -> str:
    return (CENTRAL_ROOT or "/tmp/central").strip() or "/tmp/central"


def _governance_path() -> Path:
    return Path(_root()) / "config" / GOVERNANCE_FILENAME


def _provider_secrets_path() -> Path:
    return Path(_root()) / "secrets" / PROVIDER_SECRETS_FILENAME


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("inference_governance: read failed %s", path, exc_info=True)
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_governance_config() -> dict[str, Any]:
    return _read_json(_governance_path())


def save_governance_config(data: dict[str, Any]) -> dict[str, Any]:
    _write_json(_governance_path(), data)
    return data


_migrated_legacy_vault = False


def _ensure_secrets_migrated() -> None:
    global _migrated_legacy_vault
    if _migrated_legacy_vault:
        return
    _migrated_legacy_vault = True
    from app.shared.local_vault import migrate_legacy_vault_to_admin

    migrate_legacy_vault_to_admin()
    secrets_dir = _provider_secrets_path().parent
    if secrets_dir.is_dir():
        migrate_plaintext_at_rest(secrets_dir)
    migrate_filesystem_secrets_to_backend()


def load_provider_secrets() -> dict[str, str]:
    _ensure_secrets_migrated()
    return load_provider_secrets_from_backend()


def save_provider_secret(provider_id: str, api_key: str) -> None:
    pid = (provider_id or "").strip().lower()
    if pid not in KNOWN_PROVIDERS:
        raise ValueError("provider_unknown")
    save_provider_secret_to_backend(pid, api_key)


def _provider_api_key(provider_id: str) -> str:
    pid = (provider_id or "").strip().lower()
    meta = KNOWN_PROVIDERS.get(pid)
    if not meta:
        return ""
    env_key = str(meta.get("env_key") or "")
    if env_key:
        env_val = os.getenv(env_key, "").strip()
        if env_val:
            return env_val
    return load_provider_secrets().get(pid, "")


def is_provider_configured(provider_id: str) -> bool:
    pid = (provider_id or "").strip().lower()
    cfg = load_governance_config()
    providers_cfg = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    entry = providers_cfg.get(pid) if isinstance(providers_cfg, dict) else None
    if isinstance(entry, dict) and entry.get("enabled") is False:
        return False
    return bool(_provider_api_key(pid))


def list_providers_public() -> list[dict[str, Any]]:
    cfg = load_governance_config()
    providers_cfg = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    items: list[dict[str, Any]] = []
    for pid, meta in KNOWN_PROVIDERS.items():
        entry = providers_cfg.get(pid) if isinstance(providers_cfg, dict) else {}
        enabled_flag = True
        if isinstance(entry, dict) and entry.get("enabled") is False:
            enabled_flag = False
        configured = bool(_provider_api_key(pid)) and enabled_flag
        if _env_key_configured(pid):
            source = "env"
        elif configured:
            backend_id = secret_backend_info().get("backend_id", "filesystem")
            source = "vault" if backend_id == "filesystem" else str(backend_id)
        else:
            source = "none"
        items.append(
            {
                "id": pid,
                "label": str(meta.get("label") or pid),
                "configured": configured,
                "enabled": enabled_flag,
                "source": source,
            }
        )
    return items


def _env_key_configured(provider_id: str) -> bool:
    meta = KNOWN_PROVIDERS.get(provider_id, {})
    env_key = str(meta.get("env_key") or "")
    return bool(env_key and os.getenv(env_key, "").strip())


def configure_provider(provider_id: str, *, api_key: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
    pid = (provider_id or "").strip().lower()
    if pid not in KNOWN_PROVIDERS:
        raise ValueError("provider_unknown")
    cfg = load_governance_config()
    providers_cfg = dict(cfg.get("providers") or {}) if isinstance(cfg.get("providers"), dict) else {}
    entry = dict(providers_cfg.get(pid) or {}) if isinstance(providers_cfg.get(pid), dict) else {}
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    providers_cfg[pid] = entry
    cfg["providers"] = providers_cfg
    save_governance_config(cfg)
    if api_key is not None:
        save_provider_secret(pid, api_key)
    return list_providers_public_item(pid)


def list_providers_public_item(provider_id: str) -> dict[str, Any]:
    for item in list_providers_public():
        if item["id"] == provider_id:
            return item
    raise ValueError("provider_unknown")


def get_global_models_allowlist() -> frozenset[str] | None:
    """Non-empty allowlist from env + governance file. None = unrestricted."""
    ids: set[str] = set(CENTRAL_CLOUD_MODEL_ALLOWLIST)
    cfg = load_governance_config()
    extra = cfg.get("global_models_allowlist")
    if isinstance(extra, list):
        for m in extra:
            s = str(m).strip()
            if s:
                ids.add(s)
    if not ids:
        return None
    return frozenset(ids)


def set_global_models_allowlist(model_ids: list[str]) -> list[str]:
    cleaned = sorted({str(m).strip() for m in model_ids if str(m).strip()})
    cfg = load_governance_config()
    cfg["global_models_allowlist"] = cleaned
    save_governance_config(cfg)
    return cleaned


def get_tenant_models_allowlist(tenant_id: str | None = None) -> frozenset[str] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    try:
        from app.tenant import get_tenant_config

        cfg = get_tenant_config(tid)
        if cfg and isinstance(cfg.features_json, dict):
            raw = cfg.features_json.get("models_allowlist")
            if isinstance(raw, list) and raw:
                return frozenset(str(m).strip() for m in raw if str(m).strip())
    except Exception:
        logger.debug("tenant models_allowlist load failed", exc_info=True)
    return None


def get_policy_models_allowlist(tenant_id: str | None = None) -> frozenset[str] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    policies = _load_tenant_policies(tid)
    models = policies.get("models") if isinstance(policies.get("models"), dict) else {}
    allowlist = models.get("allowlist") if isinstance(models, dict) else []
    if isinstance(allowlist, list) and allowlist:
        return frozenset(str(m).strip() for m in allowlist if str(m).strip())
    return None


def _intersect_allowlists(*sets: frozenset[str] | None) -> frozenset[str] | None:
    active = [s for s in sets if s is not None and len(s) > 0]
    if not active:
        return None
    result = active[0]
    for s in active[1:]:
        result = result & s
    return result if result else frozenset()


def model_supported_by_providers(model_id: str) -> bool:
    mid = (model_id or "").strip()
    if not mid:
        return False
    if is_provider_configured("openrouter"):
        return True
    prefix = mid.split("/", 1)[0].lower() + "/"
    for pid, meta in KNOWN_PROVIDERS.items():
        if pid == "openrouter":
            continue
        if not is_provider_configured(pid):
            continue
        prefixes = meta.get("prefixes") or ()
        for p in prefixes:
            if mid.startswith(str(p)) or prefix == str(p).lower():
                return True
    return False


def any_cloud_provider_configured() -> bool:
    return any(is_provider_configured(pid) for pid in KNOWN_PROVIDERS)


def filter_vendor_catalog(
    vendor_rows: list[dict[str, str]],
    *,
    tenant_id: str | None = None,
) -> list[dict[str, str]]:
    allowed = _intersect_allowlists(
        get_global_models_allowlist(),
        get_tenant_models_allowlist(tenant_id),
        get_policy_models_allowlist(tenant_id),
    )
    out: list[dict[str, str]] = []
    for row in vendor_rows:
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        if allowed is not None and mid not in allowed:
            continue
        if not model_supported_by_providers(mid):
            continue
        out.append(row)
    return out


def merge_user_cloud_models(
    vendor_rows: list[dict[str, str]],
    user_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for vr in sorted(vendor_rows, key=lambda x: (x.get("label") or x.get("id") or "").lower()):
        mid = vr["id"]
        if mid in seen:
            continue
        seen.add(mid)
        user_entry = user_map.get(mid)
        entry: dict[str, Any] = {
            "id": mid,
            "label": user_entry["label"] if user_entry and user_entry.get("label") else (vr.get("label") or mid),
            "enabled": user_entry["enabled"] if user_entry is not None else True,
        }
        ctx = vr.get("context_length")
        if ctx:
            try:
                entry["context_length"] = int(ctx)
            except (TypeError, ValueError):
                pass
        models.append(entry)
    return models


def effective_catalog_ids(
    vendor_rows: list[dict[str, str]],
    *,
    tenant_id: str | None = None,
) -> frozenset[str]:
    filtered = filter_vendor_catalog(vendor_rows, tenant_id=tenant_id)
    return frozenset(str(r["id"]).strip() for r in filtered if str(r.get("id") or "").strip())


def check_model_allowed(model_id: str, *, tenant_id: str | None = None) -> ModelAllowResult:
    mid = (model_id or "").strip()
    if not mid:
        return ModelAllowResult(allowed=True)

    global_al = get_global_models_allowlist()
    if global_al is not None and mid not in global_al:
        return ModelAllowResult(
            allowed=False,
            code="policy_model_denied",
            message_pt=f"Modelo não está na allowlist global: {mid}",
        )

    tenant_al = get_tenant_models_allowlist(tenant_id)
    if tenant_al is not None and mid not in tenant_al:
        return ModelAllowResult(
            allowed=False,
            code="model_not_in_tenant_catalog",
            message_pt=f"Modelo não permitido para este tenant: {mid}",
        )

    policy_al = get_policy_models_allowlist(tenant_id)
    if policy_al is not None and mid not in policy_al:
        return ModelAllowResult(
            allowed=False,
            code="policy_model_denied",
            message_pt=f"Modelo não permitido pela política: {mid}",
        )

    if not model_supported_by_providers(mid):
        return ModelAllowResult(
            allowed=False,
            code="provider_not_configured",
            message_pt=f"Nenhum provedor configurado para o modelo: {mid}",
        )

    return ModelAllowResult(allowed=True)


def assert_model_allowed(model_id: str, *, tenant_id: str | None = None) -> None:
    result = check_model_allowed(model_id, tenant_id=tenant_id)
    if not result.allowed:
        raise ValueError(result.code or "policy_model_denied")


def validate_tenant_models_allowlist(model_ids: list[str]) -> None:
    """Tenant allowlist must be subset of global (when global is set)."""
    global_al = get_global_models_allowlist()
    if global_al is None:
        return
    for mid in model_ids:
        s = str(mid).strip()
        if s and s not in global_al:
            raise ValueError(f"model_not_in_global_allowlist:{s}")


def validate_user_cloud_models_payload(
    models: list[dict[str, Any]],
    allowed_ids: frozenset[str],
) -> None:
    if not allowed_ids and models:
        raise ValueError("model_not_in_tenant_catalog")
    for m in models:
        mid = str(m.get("id") or "").strip()
        if not mid:
            raise ValueError("model_id_required")
        if mid not in allowed_ids:
            raise ValueError("model_not_in_tenant_catalog")


def governance_summary(*, tenant_id: str | None = None) -> dict[str, Any]:
    providers = list_providers_public()
    configured = sum(1 for p in providers if p.get("configured"))
    global_al = get_global_models_allowlist()
    tenant_al = get_tenant_models_allowlist(tenant_id)
    return {
        "providers": providers,
        "providers_configured": configured,
        "providers_total": len(providers),
        "global_allowlist_count": len(global_al) if global_al else 0,
        "global_allowlist_restricted": global_al is not None,
        "tenant_allowlist_count": len(tenant_al) if tenant_al else 0,
        "tenant_allowlist_restricted": tenant_al is not None,
        "openrouter_env": bool((OPENROUTER_API_KEY or "").strip()),
    }
