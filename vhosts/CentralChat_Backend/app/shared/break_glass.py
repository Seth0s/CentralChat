"""H3 — Break-glass admin override (audited, 1h TTL)."""

from __future__ import annotations

import fnmatch
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.audit_service import append_audit_event
from app.config import CENTRAL_BREAK_GLASS_TTL_HOURS
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_break_glass_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS break_glass_grants (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                path_pattern TEXT NOT NULL,
                reason TEXT NOT NULL,
                granted_by TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS break_glass_tenant_user_idx "
            "ON break_glass_grants (tenant_id, user_id, expires_at DESC);"
        )


def grant_break_glass(
    *,
    path_pattern: str,
    reason: str,
    user_id: str | None = None,
    tenant_id: str | None = None,
    ttl_hours: float | None = None,
    granted_by: str | None = None,
) -> dict[str, Any] | None:
    """Admin-only break-glass grant; audited on create."""
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    uid = (user_id or get_current_sub() or "").strip()
    pat = (path_pattern or "").strip()
    why = (reason or "").strip()
    if not uid or not pat or not why:
        return None
    ttl = float(ttl_hours if ttl_hours is not None else CENTRAL_BREAK_GLASS_TTL_HOURS)
    ttl = max(0.25, min(24.0, ttl))
    expires = _utc_now() + timedelta(hours=ttl)
    actor = (granted_by or get_current_sub() or "system").strip()
    try:
        ensure_break_glass_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO break_glass_grants
                   (tenant_id, user_id, path_pattern, reason, granted_by, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   RETURNING id::text, expires_at::text, created_at::text""",
                (tid, uid, pat[:500], why[:2000], actor[:200], expires.isoformat()),
            )
            row = cur.fetchone()
        if not row:
            return None
        grant = {
            "id": str(row[0]),
            "tenant_id": tid,
            "user_id": uid,
            "path_pattern": pat,
            "reason": why,
            "granted_by": actor,
            "expires_at": str(row[1]),
            "created_at": str(row[2]),
            "ttl_hours": ttl,
        }
        append_audit_event(
            action="break_glass.granted",
            tenant_id=tid,
            user_id=uid,
            resource=pat,
            metadata=grant,
        )
        return grant
    except Exception:
        logger.debug("grant_break_glass failed", exc_info=True)
        return None


def revoke_break_glass(grant_id: str, *, tenant_id: str | None = None) -> bool:
    if not memory_db_enabled():
        return False
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    gid = (grant_id or "").strip()
    if not gid:
        return False
    try:
        UUID(gid)
    except ValueError:
        return False
    try:
        ensure_break_glass_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE break_glass_grants SET revoked_at=now()
                   WHERE id=%s::uuid AND tenant_id=%s AND revoked_at IS NULL
                   RETURNING user_id, path_pattern""",
                (gid, tid),
            )
            row = cur.fetchone()
        if not row:
            return False
        append_audit_event(
            action="break_glass.revoked",
            tenant_id=tid,
            user_id=str(row[0]),
            resource=str(row[1]),
            metadata={"grant_id": gid},
        )
        return True
    except Exception:
        logger.debug("revoke_break_glass failed", exc_info=True)
        return False


def list_active_break_glass(*, tenant_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    if not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    now = _utc_now().isoformat()
    clauses = ["tenant_id=%s", "revoked_at IS NULL", "expires_at > %s"]
    params: list[Any] = [tid, now]
    if user_id:
        clauses.append("user_id=%s")
        params.append(user_id.strip())
    where = " AND ".join(clauses)
    try:
        ensure_break_glass_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT id::text, user_id, path_pattern, reason, granted_by,
                    expires_at::text, created_at::text
                    FROM break_glass_grants WHERE {where}
                    ORDER BY expires_at ASC""",
                params,
            )
            return [
                {
                    "id": str(r[0]),
                    "user_id": str(r[1]),
                    "path_pattern": str(r[2]),
                    "reason": str(r[3]),
                    "granted_by": str(r[4]),
                    "expires_at": str(r[5]),
                    "created_at": str(r[6]),
                }
                for r in cur.fetchall()
            ]
    except Exception:
        logger.debug("list_active_break_glass failed", exc_info=True)
        return []


def break_glass_allows_path(
    path: str,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    """Return matching active grant if path is covered, else None."""
    uid = (user_id or get_current_sub() or "").strip()
    if not uid:
        return None
    norm = (path or "").strip().replace("\\", "/")
    if not norm:
        return None
    for grant in list_active_break_glass(tenant_id=tenant_id, user_id=uid):
        pat = str(grant.get("path_pattern") or "")
        if pat and (fnmatch.fnmatch(norm, pat) or norm.startswith(pat.rstrip("/"))):
            return grant
    return None


def record_break_glass_use(grant: dict[str, Any], *, path: str, tool: str | None = None) -> None:
    append_audit_event(
        action="break_glass.used",
        tenant_id=str(grant.get("tenant_id") or resolve_pg_tenant_id()),
        user_id=str(grant.get("user_id") or ""),
        resource=path,
        metadata={
            "grant_id": grant.get("id"),
            "path_pattern": grant.get("path_pattern"),
            "tool": tool,
        },
    )
    try:
        import logging

        logging.getLogger(__name__).warning(
            "BREAK_GLASS_USED tenant=%s user=%s path=%s tool=%s grant=%s",
            grant.get("tenant_id"),
            grant.get("user_id"),
            path,
            tool,
            grant.get("id"),
        )
        from app.siem_dispatcher import dispatch_siem_event

        dispatch_siem_event(
            action="break_glass.used",
            tenant_id=str(grant.get("tenant_id") or resolve_pg_tenant_id()),
            metadata={
                "user_id": grant.get("user_id"),
                "path": path,
                "tool": tool,
                "grant_id": grant.get("id"),
            },
        )
        from app.shared.alerting import send_ops_alert

        send_ops_alert(
            action="break_glass.used",
            text=(
                f"BREAK-GLASS tenant={grant.get('tenant_id')} user={grant.get('user_id')} "
                f"path={path} tool={tool}"
            ),
            metadata={"grant_id": grant.get("id")},
        )
    except Exception:
        pass
