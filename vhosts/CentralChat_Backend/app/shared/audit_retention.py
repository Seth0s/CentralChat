"""C3 — Audit log retention (D-AUDIT-1: default 1 year per tenant)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import CENTRAL_AUDIT_RETENTION_DAYS
from app.shared.pg_tenant import connect_pg, memory_db_enabled

logger = logging.getLogger(__name__)


def _tenant_retention_days(tenant_id: str) -> int:
    if not memory_db_enabled():
        return CENTRAL_AUDIT_RETENTION_DAYS
    try:
        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT features_json FROM tenant_config WHERE tenant_id=%s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                fj = row[0]
                if isinstance(fj, str):
                    fj = json.loads(fj)
                if isinstance(fj, dict):
                    comp = fj.get("compliance")
                    if isinstance(comp, dict):
                        days = comp.get("audit_retention_days")
                        if isinstance(days, int) and days > 0:
                            return days
                    pol = fj.get("policies")
                    if isinstance(pol, dict):
                        comp = pol.get("compliance")
                        if isinstance(comp, dict):
                            days = comp.get("audit_retention_days")
                            if isinstance(days, int) and days > 0:
                                return days
    except Exception:
        logger.debug("tenant retention lookup failed", exc_info=True)
    return CENTRAL_AUDIT_RETENTION_DAYS


def purge_expired_audit_events(*, dry_run: bool = False) -> dict[str, Any]:
    """Delete audit_events older than tenant retention. Returns per-tenant counts."""
    if not memory_db_enabled():
        return {"deleted": 0, "tenants": {}}
    now = datetime.now(timezone.utc)
    tenants: dict[str, int] = {}
    total = 0
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT tenant_id FROM audit_events")
        tenant_ids = [str(r[0]) for r in cur.fetchall() if r and r[0]]
    for tid in tenant_ids or ["default"]:
        days = _tenant_retention_days(tid)
        cutoff = (now - timedelta(days=days)).isoformat()
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM audit_events WHERE tenant_id=%s AND created_at < %s",
                (tid, cutoff),
            )
            n = int(cur.fetchone()[0] or 0)
            if n and not dry_run:
                cur.execute(
                    "DELETE FROM audit_events WHERE tenant_id=%s AND created_at < %s",
                    (tid, cutoff),
                )
            tenants[tid] = n
            total += n
    return {"deleted": total if not dry_run else 0, "would_delete": total, "tenants": tenants}
