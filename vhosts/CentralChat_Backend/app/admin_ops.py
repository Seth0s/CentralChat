"""P5 — Deployment / ops status snapshot for admin UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import (
    AGENT_TOOLS_ENABLED,
    CENTRAL_AIR_GAP_MODE,
    CENTRAL_APP_ENV,
    CENTRAL_DATA_RESIDENCY,
    CENTRAL_JWT_MODE,
    CENTRAL_LLM_ENDPOINT_REGION,
    CENTRAL_TELEMETRY_DISABLED,
    CHAT_SESSIONS_ENABLED,
    PLAYBOOK_FEATURE_ENABLED,
    WIDGET_MULTI_SLOT_ENABLED,
)
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.secret_backends import secret_backend_info
from app.shared.secret_resolver import integration_secrets_configured, resolve_siem_webhook_urls
from app.shared.siem_outbox import siem_outbox_summary


def _migration_status() -> dict[str, Any]:
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    files = sorted(f.name for f in migrations_dir.glob("*.sql") if f.name[0].isdigit())
    applied: list[str] = []
    if memory_db_enabled():
        try:
            with connect_pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS _migrations (
                        filename TEXT PRIMARY KEY,
                        executed_at TIMESTAMPTZ NOT NULL DEFAULT now());"""
                )
                cur.execute("SELECT filename FROM _migrations ORDER BY filename")
                applied = [str(r[0]) for r in cur.fetchall()]
        except Exception:
            applied = []
    pending = [name for name in files if name not in set(applied)]
    return {
        "total_files": len(files),
        "applied_count": len(applied),
        "pending_count": len(pending),
        "pending": pending[:10],
    }


def build_deploy_status(*, tenant_id: str | None = None) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    postgres_status = "disabled"
    if memory_db_enabled():
        try:
            with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            postgres_status = "ok"
        except Exception as exc:
            postgres_status = f"error:{str(exc)[:120]}"
    siem = siem_outbox_summary(tenant_id=tid)
    migrations = _migration_status()
    return {
        "tenant_id": tid,
        "environment": CENTRAL_APP_ENV,
        "health": {
            "postgres": postgres_status,
            "memory_db_enabled": memory_db_enabled(),
        },
        "residency": {
            "data_residency": CENTRAL_DATA_RESIDENCY,
            "llm_endpoint_region": CENTRAL_LLM_ENDPOINT_REGION,
            "telemetry_disabled": CENTRAL_TELEMETRY_DISABLED,
            "air_gap_mode": CENTRAL_AIR_GAP_MODE,
        },
        "feature_flags": {
            "jwt_mode": CENTRAL_JWT_MODE,
            "agent_tools_enabled": AGENT_TOOLS_ENABLED,
            "chat_sessions_enabled": CHAT_SESSIONS_ENABLED,
            "widget_multi_slot_enabled": WIDGET_MULTI_SLOT_ENABLED,
            "playbook_feature_enabled": PLAYBOOK_FEATURE_ENABLED,
        },
        "siem": {
            **siem,
            "webhook_urls_count": len(resolve_siem_webhook_urls()),
            "integration_secrets": integration_secrets_configured(),
        },
        "migrations": migrations,
        "secrets_storage": secret_backend_info(),
        "backup": {
            "status": "not_configured",
            "last_restore_tested_at": None,
            "note_pt": "Backup/restore monitor requer integração externa; configure via deploy.",
        },
    }
