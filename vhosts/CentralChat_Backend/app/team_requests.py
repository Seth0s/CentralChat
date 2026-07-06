"""Contextual team requests — communication with lead/admin without blocking local work."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.audit_service import append_audit_event
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)

VALID_REQUEST_TYPES = frozenset(
    {
        "lead_decision",
        "admin_exception",
        "compliance_question",
        "policy_exception",
        "shared_resource_change",
        "central_repo_change",
    }
)
VALID_REQUEST_STATUS = frozenset({"open", "in_discussion", "resolved", "cancelled"})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid_or_none(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def _user_uuid(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def ensure_team_requests_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS team_requests (
                id UUID PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                title TEXT NOT NULL,
                body TEXT,
                requester_id UUID NOT NULL,
                assignee_id UUID,
                project_id UUID,
                session_id TEXT,
                work_item_id TEXT,
                resolution TEXT,
                resolved_by UUID,
                resolved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS team_requests_tenant_status_idx "
            "ON team_requests (tenant_id, status, updated_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS team_requests_tenant_project_idx "
            "ON team_requests (tenant_id, project_id, status);"
        )
        cur.execute("ALTER TABLE team_requests ENABLE ROW LEVEL SECURITY;")
        cur.execute("DROP POLICY IF EXISTS team_requests_tenant_rls ON team_requests;")
        cur.execute(
            """CREATE POLICY team_requests_tenant_rls ON team_requests
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS team_request_comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                request_id UUID NOT NULL,
                author_id UUID NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY (request_id) REFERENCES team_requests (id) ON DELETE CASCADE
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS team_request_comments_tenant_request_idx "
            "ON team_request_comments (tenant_id, request_id, created_at);"
        )
        cur.execute("ALTER TABLE team_request_comments ENABLE ROW LEVEL SECURITY;")
        cur.execute("DROP POLICY IF EXISTS team_request_comments_tenant_rls ON team_request_comments;")
        cur.execute(
            """CREATE POLICY team_request_comments_tenant_rls ON team_request_comments
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )


def _row_to_request(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "request_type": str(row[2]),
        "status": str(row[3]),
        "title": str(row[4]),
        "body": str(row[5] or ""),
        "requester_id": str(row[6]) if row[6] else None,
        "assignee_id": str(row[7]) if row[7] else None,
        "project_id": str(row[8]) if row[8] else None,
        "session_id": row[9],
        "work_item_id": row[10],
        "resolution": str(row[11] or "") if row[11] else None,
        "resolved_by": str(row[12]) if row[12] else None,
        "resolved_at": str(row[13] or "") if row[13] else None,
        "created_at": str(row[14] or ""),
        "updated_at": str(row[15] or ""),
    }


def create_team_request(
    *,
    request_type: str,
    title: str,
    body: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    work_item_id: str | None = None,
    assignee_id: str | None = None,
    requester_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    rtype = (request_type or "").strip().lower()
    if rtype not in VALID_REQUEST_TYPES:
        raise ValueError("invalid_request_type")
    t = (title or "").strip()
    if not t:
        raise ValueError("empty_title")
    requester = _user_uuid(requester_id or get_current_sub())
    if not requester:
        raise ValueError("requester_required")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    rid = str(uuid4())
    now = _utc_iso()
    assignee = _user_uuid(assignee_id)
    project = _uuid_or_none(project_id)
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_requests
               (id, tenant_id, request_type, status, title, body, requester_id, assignee_id,
                project_id, session_id, work_item_id, created_at, updated_at)
               VALUES (%s,%s,%s,'open',%s,%s,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s)
               RETURNING id, tenant_id, request_type, status, title, body, requester_id,
                         assignee_id, project_id, session_id, work_item_id, resolution,
                         resolved_by, resolved_at, created_at, updated_at""",
            (
                rid,
                tid,
                rtype,
                t[:500],
                (body or "")[:4000] or None,
                requester,
                assignee,
                project,
                (session_id or "").strip() or None,
                (work_item_id or "").strip() or None,
                now,
                now,
            ),
        )
        row = cur.fetchone()
    item = _row_to_request(row)
    append_audit_event(
        action="team_request.created",
        tenant_id=tid,
        user_id=requester,
        resource=rid,
        metadata={"request_type": rtype, "project_id": project, "session_id": session_id},
    )
    return item


def list_team_requests(
    *,
    status: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    if not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    clauses = ["tenant_id=%s"]
    params: list[Any] = [tid]
    if status and status in VALID_REQUEST_STATUS:
        clauses.append("status=%s")
        params.append(status)
    if project_id:
        pid = _uuid_or_none(project_id)
        if pid:
            clauses.append("project_id=%s::uuid")
            params.append(pid)
    params.append(max(1, min(300, int(limit))))
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, tenant_id, request_type, status, title, body, requester_id,
                       assignee_id, project_id, session_id, work_item_id, resolution,
                       resolved_by, resolved_at, created_at, updated_at
                FROM team_requests
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC
                LIMIT %s""",
            params,
        )
        return [_row_to_request(r) for r in cur.fetchall()]


def get_team_request(request_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    rid = (request_id or "").strip()
    if not rid or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, request_type, status, title, body, requester_id,
                      assignee_id, project_id, session_id, work_item_id, resolution,
                      resolved_by, resolved_at, created_at, updated_at
               FROM team_requests WHERE tenant_id=%s AND id=%s::uuid LIMIT 1""",
            (tid, rid),
        )
        row = cur.fetchone()
    return _row_to_request(row) if row else None


def resolve_team_request(
    request_id: str,
    *,
    resolution: str,
    status: str = "resolved",
    resolver_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    rid = (request_id or "").strip()
    text = (resolution or "").strip()
    st = (status or "resolved").strip().lower()
    if not rid or not text:
        raise ValueError("invalid_resolution")
    if st not in VALID_REQUEST_STATUS:
        raise ValueError("invalid_status")
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    resolver = _user_uuid(resolver_id or get_current_sub())
    now = _utc_iso()
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE team_requests
               SET status=%s, resolution=%s, resolved_by=%s::uuid, resolved_at=%s, updated_at=%s
               WHERE tenant_id=%s AND id=%s::uuid
               RETURNING id, tenant_id, request_type, status, title, body, requester_id,
                         assignee_id, project_id, session_id, work_item_id, resolution,
                         resolved_by, resolved_at, created_at, updated_at""",
            (st, text[:4000], resolver, now, now, tid, rid),
        )
        row = cur.fetchone()
    if not row:
        return None
    item = _row_to_request(row)
    append_audit_event(
        action="team_request.resolved",
        tenant_id=tid,
        user_id=resolver,
        resource=rid,
        metadata={"status": st},
    )
    return item


def add_team_request_comment(
    request_id: str,
    *,
    body: str,
    author_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    rid = (request_id or "").strip()
    text = (body or "").strip()
    if not rid or not text:
        raise ValueError("empty_comment")
    author = _user_uuid(author_id or get_current_sub())
    if not author:
        raise ValueError("author_required")
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not get_team_request(rid, tenant_id=tid):
        raise ValueError("request_not_found")
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_request_comments (tenant_id, request_id, author_id, body)
               VALUES (%s,%s::uuid,%s::uuid,%s)
               RETURNING id::text, tenant_id, request_id::text, author_id::text, body, created_at::text""",
            (tid, rid, author, text[:4000]),
        )
        row = cur.fetchone()
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "request_id": str(row[2]),
        "author_id": str(row[3]),
        "body": str(row[4]),
        "created_at": str(row[5] or ""),
    }


def list_team_request_comments(request_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    rid = (request_id or "").strip()
    if not rid or not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_team_requests_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, request_id::text, author_id::text, body, created_at::text
               FROM team_request_comments
               WHERE tenant_id=%s AND request_id=%s::uuid
               ORDER BY created_at""",
            (tid, rid),
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]),
            "request_id": str(r[2]),
            "author_id": str(r[3]),
            "body": str(r[4]),
            "created_at": str(r[5] or ""),
        }
        for r in rows
    ]
