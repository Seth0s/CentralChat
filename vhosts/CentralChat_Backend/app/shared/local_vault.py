"""
K.3 — cofre local: segredos de integracao em ficheiro fora do repositorio (CENTRAL_ROOT/state/).

- Nunca escrever valores do cofre em audit/logs.
- So chaves conhecidas sao lidas (lista explicita).
- Preferir secrets admin (CENTRAL_ROOT/secrets/) — este modulo delega quando possivel.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Chaves permitidas no JSON legado (snake_case).
_VAULT_KEY_ALLOWLIST = frozenset(
    {
        "gemini_api_key",
        "openrouter_api_key",
        "deepseek_api_key",
    }
)

# Mapeamento cofre legado → provider id no admin.
_VAULT_KEY_TO_PROVIDER: dict[str, str] = {
    "openrouter_api_key": "openrouter",
    "gemini_api_key": "google",
    "deepseek_api_key": "deepseek",
}


_legacy_vault_warned = False


def _warn_legacy_vault_use(vault_key: str) -> None:
    global _legacy_vault_warned
    if _legacy_vault_warned:
        return
    _legacy_vault_warned = True
    logger.warning(
        "local_vault: legacy state/secrets/vault.json is deprecated; "
        "use admin secrets (CENTRAL_ROOT/secrets/). key=%s",
        vault_key,
    )


def _archive_legacy_vault(vault_path: str) -> None:
    if not vault_path or not os.path.isfile(vault_path):
        return
    archived = f"{vault_path}.migrated"
    if os.path.isfile(archived):
        return
    try:
        os.rename(vault_path, archived)
        logger.info("local_vault: archived legacy vault to %s", archived)
    except OSError:
        logger.debug("local_vault: archive failed path=%s", vault_path, exc_info=True)


def read_vault_file(vault_path: str) -> dict[str, str]:
    """Le JSON plano; devolve apenas entradas string na allowlist."""
    if not vault_path or not os.path.isfile(vault_path):
        return {}
    try:
        with open(vault_path, encoding="utf-8") as f:
            raw: Any = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k not in _VAULT_KEY_ALLOWLIST:
            continue
        if isinstance(v, str):
            out[str(k)] = v.strip()
    return out


def _resolve_from_admin_provider(vault_key: str) -> str:
    provider_id = _VAULT_KEY_TO_PROVIDER.get(vault_key)
    if not provider_id:
        return ""
    try:
        from app.shared.inference_governance import _provider_api_key

        return (_provider_api_key(provider_id) or "").strip()
    except Exception:
        logger.debug("local_vault: admin provider resolve failed for %s", vault_key, exc_info=True)
        return ""


def resolve_secret(*, env_value: str, vault_path: str, vault_key: str) -> str:
    """
    Prioridade: variavel de ambiente > admin providers > cofre legado JSON.
    vault_key deve estar em _VAULT_KEY_ALLOWLIST.
    """
    ev = (env_value or "").strip()
    if ev:
        return ev
    if vault_key not in _VAULT_KEY_ALLOWLIST:
        return ""
    admin_val = _resolve_from_admin_provider(vault_key)
    if admin_val:
        return admin_val
    secrets = read_vault_file(vault_path)
    legacy_val = (secrets.get(vault_key) or "").strip()
    if legacy_val:
        _warn_legacy_vault_use(vault_key)
    return legacy_val


def migrate_legacy_vault_to_admin() -> int:
    """
    Migra chaves do cofre legado (state/secrets/vault.json) para inference_providers.json.
    Nao sobrescreve providers ja configurados via admin ou env.
    """
    try:
        from app.config import SECRETS_VAULT_PATH
        from app.shared.inference_governance import (
            KNOWN_PROVIDERS,
            is_provider_configured,
            save_provider_secret,
        )
    except Exception:
        logger.debug("local_vault: migration skipped (imports)", exc_info=True)
        return 0

    vault_path = (SECRETS_VAULT_PATH or "").strip()
    if not vault_path or not os.path.isfile(vault_path):
        return 0

    legacy = read_vault_file(vault_path)
    if not legacy:
        return 0

    migrated = 0
    for vault_key, provider_id in _VAULT_KEY_TO_PROVIDER.items():
        if provider_id not in KNOWN_PROVIDERS:
            continue
        value = (legacy.get(vault_key) or "").strip()
        if not value:
            continue
        if is_provider_configured(provider_id):
            continue
        try:
            save_provider_secret(provider_id, value)
            migrated += 1
            logger.info("local_vault: migrated %s → provider:%s", vault_key, provider_id)
        except Exception:
            logger.debug("local_vault: migration failed for %s", vault_key, exc_info=True)
    if migrated > 0:
        _archive_legacy_vault(vault_path)
    return migrated
