"""Secrets Vault — encrypted API keys and sensitive config.

TEAM mode: PostgreSQL (table secrets, AES-256-GCM encrypted).
SOLO mode: ~/.central/vault.json (same encryption).

Encryption uses CENTRAL_JWT_SECRET (already in .env) as the master key.
Keys are tenant-scoped with RLS in TEAM mode.

Design: .env.example §NOTAS — provider keys managed by UI Admin, not env vars.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# Default vault path for SOLO mode
SOLO_VAULT_PATH = Path(os.getenv("CENTRAL_ROOT", Path.home() / ".central")) / "vault.json"


def _derive_key() -> bytes:
    """Derive 256-bit AES key from JWT secret (or fallback)."""
    raw = os.getenv("CENTRAL_JWT_SECRET", "centralchat-dev-key-change-me").encode()
    return hashlib.sha256(raw).digest()


def _encrypt(plaintext: str) -> str:
    """AES-256-GCM encrypt → base64."""
    key = _derive_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def _decrypt(encoded: str) -> str:
    """Base64 → AES-256-GCM decrypt."""
    key = _derive_key()
    raw = base64.b64decode(encoded)
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


# ═══════════════════════════════════════════════════════════════
# SOLO vault (file-based)
# ═══════════════════════════════════════════════════════════════

def _load_vault() -> dict[str, str]:
    if SOLO_VAULT_PATH.is_file():
        with open(SOLO_VAULT_PATH) as f:
            return json.load(f)
    return {}


def _save_vault(data: dict[str, str]) -> None:
    SOLO_VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SOLO_VAULT_PATH, "w") as f:
        json.dump(data, f)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def set_secret(key: str, value: str, *, tenant_id: str = "default") -> bool:
    """Store an encrypted secret. PG in TEAM, file in SOLO."""
    encrypted = _encrypt(value)
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if memory_db_enabled():
            tid = tenant_id
            with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS secrets (
                        tenant_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        encrypted_value TEXT NOT NULL,
                        updated_at TIMESTAMPTZ DEFAULT now(),
                        PRIMARY KEY (tenant_id, key)
                    );"""
                )
                cur.execute(
                    """INSERT INTO secrets (tenant_id, key, encrypted_value, updated_at)
                       VALUES (%s,%s,%s,now())
                       ON CONFLICT (tenant_id, key) DO UPDATE
                       SET encrypted_value = EXCLUDED.encrypted_value,
                           updated_at = now()""",
                    (tid, key, encrypted),
                )
            return True
    except Exception:
        logger.debug("PG secret store failed, falling back to file", exc_info=True)

    # SOLO fallback
    vault = _load_vault()
    vault[key] = encrypted
    _save_vault(vault)
    return True


def get_secret(key: str, *, tenant_id: str = "default") -> str | None:
    """Retrieve and decrypt a secret. Tries PG first, then file vault."""
    # Try PG
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if memory_db_enabled():
            tid = tenant_id
            with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT encrypted_value FROM secrets WHERE tenant_id=%s AND key=%s",
                    (tid, key),
                )
                row = cur.fetchone()
                if row:
                    try:
                        return _decrypt(row[0])
                    except Exception:
                        logger.debug("PG secret decrypt failed for key=%s", key)
    except Exception:
        logger.debug("PG secret read failed, trying file", exc_info=True)

    # SOLO fallback: file vault
    vault = _load_vault()
    encrypted = vault.get(key)
    if encrypted:
        try:
            return _decrypt(encrypted)
        except Exception:
            logger.debug("File vault decrypt failed for key=%s", key)
    return None


def delete_secret(key: str, *, tenant_id: str = "default") -> bool:
    """Delete a secret."""
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if memory_db_enabled():
            with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM secrets WHERE tenant_id=%s AND key=%s",
                    (tenant_id, key),
                )
            return True
    except Exception:
        logger.debug("PG secret delete failed", exc_info=True)

    vault = _load_vault()
    vault.pop(key, None)
    _save_vault(vault)
    return True


def list_secrets(*, tenant_id: str = "default") -> list[str]:
    """List secret keys (never values)."""
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if memory_db_enabled():
            with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT key FROM secrets WHERE tenant_id=%s ORDER BY key",
                    (tenant_id,),
                )
                return [r[0] for r in cur.fetchall()]
    except Exception:
        pass
    return list(_load_vault().keys())
