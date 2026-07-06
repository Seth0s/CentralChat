"""P5 — Async audit export jobs for large volumes."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.audit_service import append_audit_event, export_audit_csv, export_audit_json, list_audit_events
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)

MAX_ASYNC_EXPORT_ROWS = 50_000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_audit_export_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS audit_export_jobs (
                id UUID PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                format TEXT NOT NULL DEFAULT 'csv',
                since TEXT,
                user_id TEXT,
                action TEXT,
                path_prefix TEXT,
                row_count INT,
                result_text TEXT,
                error TEXT,
                requested_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS audit_export_jobs_tenant_created_idx "
            "ON audit_export_jobs (tenant_id, created_at DESC);"
        )


def create_audit_export_job(
    *,
    format: str = "csv",
    since: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    path_prefix: str | None = None,
    tenant_id: str | None = None,
    requested_by: str | None = None,
) -> dict[str, Any]:
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    fmt = (format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        raise ValueError("invalid_format")
    job_id = str(uuid4())
    requester = (requested_by or get_current_sub() or "").strip() or None
    now = _utc_iso()
    ensure_audit_export_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_export_jobs
               (id, tenant_id, status, format, since, user_id, action, path_prefix, requested_by, created_at)
               VALUES (%s::uuid,%s,'pending',%s,%s,%s,%s,%s,%s,%s)""",
            (job_id, tid, fmt, since, user_id, action, path_prefix, requester, now),
        )
    append_audit_event(
        action="audit.export_job.created",
        tenant_id=tid,
        user_id=requester,
        resource=job_id,
        metadata={"format": fmt, "since": since},
    )
    thread = threading.Thread(
        target=_run_audit_export_job,
        args=(job_id, tid),
        daemon=True,
        name=f"audit-export-{job_id[:8]}",
    )
    thread.start()
    return get_audit_export_job(job_id, tenant_id=tid) or {"id": job_id, "status": "pending"}


def _run_audit_export_job(job_id: str, tenant_id: str) -> None:
    try:
        ensure_audit_export_schema()
        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE audit_export_jobs SET status='running'
                   WHERE id=%s::uuid AND tenant_id=%s AND status='pending'""",
                (job_id, tenant_id),
            )
            cur.execute(
                """SELECT format, since, user_id, action, path_prefix
                   FROM audit_export_jobs WHERE id=%s::uuid AND tenant_id=%s""",
                (job_id, tenant_id),
            )
            row = cur.fetchone()
        if not row:
            return
        fmt, since, user_id, action, path_prefix = row
        rows = list_audit_events(
            tenant_id=tenant_id,
            since=since,
            user_id=user_id,
            action=action,
            path_prefix=path_prefix,
            limit=MAX_ASYNC_EXPORT_ROWS,
        )
        body = export_audit_csv(rows) if fmt == "csv" else export_audit_json(rows)
        now = _utc_iso()
        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE audit_export_jobs
                   SET status='completed', row_count=%s, result_text=%s, completed_at=%s
                   WHERE id=%s::uuid AND tenant_id=%s""",
                (len(rows), body, now, job_id, tenant_id),
            )
        append_audit_event(
            action="audit.export_job.completed",
            tenant_id=tenant_id,
            resource=job_id,
            metadata={"row_count": len(rows), "format": fmt},
        )
    except Exception as exc:
        logger.exception("audit export job failed", extra={"job_id": job_id})
        try:
            with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE audit_export_jobs
                       SET status='failed', error=%s, completed_at=%s
                       WHERE id=%s::uuid AND tenant_id=%s""",
                    (str(exc)[:2000], _utc_iso(), job_id, tenant_id),
                )
        except Exception:
            logger.debug("failed to mark export job failed", exc_info=True)


def get_audit_export_job(job_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    jid = (job_id or "").strip()
    if not jid or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_audit_export_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, status, format, since, user_id, action, path_prefix,
                      row_count, error, requested_by, created_at::text, completed_at::text
               FROM audit_export_jobs WHERE tenant_id=%s AND id=%s::uuid LIMIT 1""",
            (tid, jid),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "status": str(row[2]),
        "format": str(row[3]),
        "since": row[4],
        "user_id": row[5],
        "action": row[6],
        "path_prefix": row[7],
        "row_count": int(row[8]) if row[8] is not None else None,
        "error": row[9],
        "requested_by": row[10],
        "created_at": str(row[11] or ""),
        "completed_at": str(row[12] or "") if row[12] else None,
        "download_ready": str(row[2]) == "completed",
    }


def get_audit_export_result(job_id: str, *, tenant_id: str | None = None) -> str | None:
    jid = (job_id or "").strip()
    if not jid or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_audit_export_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT result_text FROM audit_export_jobs
               WHERE tenant_id=%s AND id=%s::uuid AND status='completed' LIMIT 1""",
            (tid, jid),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def list_audit_export_jobs(*, tenant_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_audit_export_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, status, format, since, row_count, error, created_at::text, completed_at::text
               FROM audit_export_jobs
               WHERE tenant_id=%s
               ORDER BY created_at DESC
               LIMIT %s""",
            (tid, max(1, min(100, int(limit)))),
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "status": str(r[1]),
            "format": str(r[2]),
            "since": r[3],
            "row_count": int(r[4]) if r[4] is not None else None,
            "error": r[5],
            "created_at": str(r[6] or ""),
            "completed_at": str(r[7] or "") if r[7] else None,
            "download_ready": str(r[1]) == "completed",
        }
        for r in rows
    ]
