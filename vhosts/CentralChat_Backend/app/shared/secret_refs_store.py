"""Postgres metadata for admin secrets (Phase 2) — no plaintext values."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def secret_fingerprint(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def secret_prefix(value: str) -> str:
    stripped = (value or "").strip()
    if len(stripped) <= 4:
        return "****"
    return f"{stripped[:4]}…"


def ensure_secret_refs_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS secret_refs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                secret_key TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'custom',
                label TEXT,
                storage_kind TEXT NOT NULL DEFAULT 'filesystem_vault',
                storage_ref TEXT,
                value_prefix TEXT,
                value_fingerprint TEXT,
                active_version_id UUID,
                configured BOOLEAN NOT NULL DEFAULT false,
                created_by TEXT,
                updated_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, secret_key)
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS provider_configs (
                tenant_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT true,
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, provider_id)
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS provider_key_versions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                secret_ref_id UUID,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                rotated_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                retired_at TIMESTAMPTZ
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS inference_provider_status (
                tenant_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                configured BOOLEAN NOT NULL DEFAULT false,
                last_test_at TIMESTAMPTZ,
                last_test_ok BOOLEAN,
                last_test_message TEXT,
                last_error_at TIMESTAMPTZ,
                last_error_message TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, provider_id)
            );"""
        )


def upsert_secret_ref(
    *,
    tenant_id: str | None = None,
    secret_key: str,
    category: str,
    label: str | None = None,
    configured: bool,
    value_prefix: str | None = None,
    value_fingerprint: str | None = None,
    storage_ref: str | None = None,
    updated_by: str | None = None,
) -> str | None:
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    key = (secret_key or "").strip().lower()
    if not key:
        return None
    ensure_secret_refs_schema()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO secret_refs (
                       tenant_id, secret_key, category, label, configured,
                       value_prefix, value_fingerprint, storage_ref,
                       created_by, updated_by, updated_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (tenant_id, secret_key) DO UPDATE SET
                       category=EXCLUDED.category,
                       label=COALESCE(EXCLUDED.label, secret_refs.label),
                       configured=EXCLUDED.configured,
                       value_prefix=EXCLUDED.value_prefix,
                       value_fingerprint=EXCLUDED.value_fingerprint,
                       storage_ref=COALESCE(EXCLUDED.storage_ref, secret_refs.storage_ref),
                       updated_by=EXCLUDED.updated_by,
                       updated_at=now()
                   RETURNING id::text""",
                (
                    tid,
                    key,
                    category,
                    label,
                    bool(configured),
                    value_prefix,
                    value_fingerprint,
                    storage_ref,
                    updated_by,
                    updated_by,
                ),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    except Exception:
        logger.debug("upsert_secret_ref failed key=%s", key, exc_info=True)
        return None


def delete_secret_ref(*, tenant_id: str | None = None, secret_key: str) -> None:
    if not memory_db_enabled():
        return
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    key = (secret_key or "").strip().lower()
    if not key:
        return
    ensure_secret_refs_schema()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM secret_refs WHERE tenant_id=%s AND secret_key=%s",
                (tid, key),
            )
    except Exception:
        logger.debug("delete_secret_ref failed key=%s", key, exc_info=True)


def record_provider_key_version(
    *,
    tenant_id: str | None = None,
    provider_id: str,
    secret_ref_id: str | None,
    api_key: str,
    rotated_by: str | None = None,
) -> None:
    if not memory_db_enabled():
        return
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    pid = (provider_id or "").strip().lower()
    fp = secret_fingerprint(api_key)
    prefix = secret_prefix(api_key)
    if not pid or not fp:
        return
    ensure_secret_refs_schema()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE provider_key_versions
                   SET status='retired', retired_at=now()
                   WHERE tenant_id=%s AND provider_id=%s AND status='active'""",
                (tid, pid),
            )
            cur.execute(
                """INSERT INTO provider_key_versions (
                       tenant_id, provider_id, secret_ref_id,
                       key_prefix, key_hash, status, rotated_by
                   ) VALUES (%s,%s,%s::uuid,%s,%s,'active',%s)
                   RETURNING id::text""",
                (tid, pid, secret_ref_id, prefix, fp, rotated_by),
            )
            version_row = cur.fetchone()
            if version_row and secret_ref_id:
                cur.execute(
                    """UPDATE secret_refs SET active_version_id=%s::uuid, updated_at=now()
                       WHERE id=%s::uuid""",
                    (str(version_row[0]), secret_ref_id),
                )
    except Exception:
        logger.debug("record_provider_key_version failed provider=%s", pid, exc_info=True)


def upsert_provider_config(
    *,
    tenant_id: str | None = None,
    provider_id: str,
    enabled: bool,
    updated_by: str | None = None,
    config_json: dict[str, Any] | None = None,
) -> None:
    if not memory_db_enabled():
        return
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    pid = (provider_id or "").strip().lower()
    if not pid:
        return
    ensure_secret_refs_schema()
    payload = config_json if isinstance(config_json, dict) else {}
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO provider_configs (tenant_id, provider_id, enabled, config_json, updated_by, updated_at)
                   VALUES (%s,%s,%s,%s::jsonb,%s,now())
                   ON CONFLICT (tenant_id, provider_id) DO UPDATE SET
                       enabled=EXCLUDED.enabled,
                       config_json=EXCLUDED.config_json,
                       updated_by=EXCLUDED.updated_by,
                       updated_at=now()""",
                (tid, pid, bool(enabled), json.dumps(payload), updated_by),
            )
    except Exception:
        logger.debug("upsert_provider_config failed provider=%s", pid, exc_info=True)


def upsert_inference_provider_status(
    *,
    tenant_id: str | None = None,
    provider_id: str,
    configured: bool,
    last_test_ok: bool | None = None,
    last_test_message: str | None = None,
) -> None:
    if not memory_db_enabled():
        return
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    pid = (provider_id or "").strip().lower()
    if not pid:
        return
    ensure_secret_refs_schema()
    now = _utc_now().isoformat()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            if last_test_ok is None:
                cur.execute(
                    """INSERT INTO inference_provider_status (tenant_id, provider_id, configured, updated_at)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (tenant_id, provider_id) DO UPDATE SET
                           configured=EXCLUDED.configured,
                           updated_at=EXCLUDED.updated_at""",
                    (tid, pid, bool(configured), now),
                )
            else:
                cur.execute(
                    """INSERT INTO inference_provider_status (
                           tenant_id, provider_id, configured,
                           last_test_at, last_test_ok, last_test_message, updated_at
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (tenant_id, provider_id) DO UPDATE SET
                           configured=EXCLUDED.configured,
                           last_test_at=EXCLUDED.last_test_at,
                           last_test_ok=EXCLUDED.last_test_ok,
                           last_test_message=EXCLUDED.last_test_message,
                           updated_at=EXCLUDED.updated_at""",
                    (tid, pid, bool(configured), now, bool(last_test_ok), last_test_message, now),
                )
    except Exception:
        logger.debug("upsert_inference_provider_status failed provider=%s", pid, exc_info=True)


def list_secret_ref_enrichment(*, tenant_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Map secret_key → PG metadata for list API enrichment."""
    if not memory_db_enabled():
        return {}
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_secret_refs_schema()
    out: dict[str, dict[str, Any]] = {}
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT secret_key, value_fingerprint, configured, updated_at::text,
                          active_version_id::text
                   FROM secret_refs WHERE tenant_id=%s""",
                (tid,),
            )
            for key, fp, configured, updated_at, active_vid in cur.fetchall():
                out[str(key)] = {
                    "value_fingerprint": fp,
                    "pg_configured": bool(configured),
                    "pg_updated_at": updated_at,
                    "active_version_id": active_vid,
                }
            cur.execute(
                """SELECT provider_id, last_test_at::text, last_test_ok, last_test_message
                   FROM inference_provider_status WHERE tenant_id=%s""",
                (tid,),
            )
            for pid, last_test_at, last_test_ok, last_test_message in cur.fetchall():
                provider_key = f"provider:{pid}"
                entry = out.setdefault(provider_key, {})
                entry["last_test_at"] = last_test_at
                entry["last_test_ok"] = last_test_ok
                entry["last_test_message"] = last_test_message
            cur.execute(
                """SELECT provider_id, COUNT(*)::int
                   FROM provider_key_versions
                   WHERE tenant_id=%s AND status='active'
                   GROUP BY provider_id""",
                (tid,),
            )
            for pid, count in cur.fetchall():
                provider_key = f"provider:{pid}"
                out.setdefault(provider_key, {})["active_version_count"] = int(count or 0)
    except Exception:
        logger.debug("list_secret_ref_enrichment failed", exc_info=True)
    return out


def sync_secret_metadata_from_item(
    item: dict[str, Any],
    *,
    tenant_id: str | None = None,
    updated_by: str | None = None,
    api_key: str | None = None,
) -> None:
    """Dual-write helper after filesystem upsert."""
    key = str(item.get("key") or "").strip().lower()
    if not key:
        return
    category = str(item.get("category") or "custom")
    label = str(item.get("label") or key)
    configured = bool(item.get("configured"))
    prefix = str(item.get("prefix") or "") or None
    fp = secret_fingerprint(api_key) if api_key else None
    ref_id = upsert_secret_ref(
        tenant_id=tenant_id,
        secret_key=key,
        category=category,
        label=label,
        configured=configured,
        value_prefix=prefix if prefix and prefix != "****" else None,
        value_fingerprint=fp,
        storage_ref=f"secrets/{key}",
        updated_by=updated_by,
    )
    if key.startswith("provider:") and api_key:
        pid = key.split(":", 1)[1]
        record_provider_key_version(
            tenant_id=tenant_id,
            provider_id=pid,
            secret_ref_id=ref_id,
            api_key=api_key,
            rotated_by=updated_by,
        )
        upsert_provider_config(
            tenant_id=tenant_id,
            provider_id=pid,
            enabled=bool(item.get("enabled", True)),
            updated_by=updated_by,
        )
        upsert_inference_provider_status(
            tenant_id=tenant_id,
            provider_id=pid,
            configured=configured,
        )
