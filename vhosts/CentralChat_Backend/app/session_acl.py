"""Session ACL — share chat sessions by user or role."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)

VALID_PRINCIPAL_TYPES = frozenset({"user", "role"})
VALID_ACCESS_LEVELS = frozenset({"read", "write", "admin"})


def _user_uuid(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def ensure_session_acl_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS chat_session_acl (
                tenant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                principal_type TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                access_level TEXT NOT NULL DEFAULT 'read',
                granted_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, session_id, principal_type, principal_id),
                CHECK (principal_type IN ('user', 'role')),
                CHECK (access_level IN ('read', 'write', 'admin'))
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS chat_session_acl_tenant_principal_idx "
            "ON chat_session_acl (tenant_id, principal_type, principal_id, access_level);"
        )
        cur.execute("ALTER TABLE chat_session_acl ENABLE ROW LEVEL SECURITY;")
        cur.execute("DROP POLICY IF EXISTS chat_session_acl_tenant_rls ON chat_session_acl;")
        cur.execute(
            """CREATE POLICY chat_session_acl_tenant_rls ON chat_session_acl
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )


def list_session_acl(*, session_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
    sid = (session_id or "").strip()
    if not sid or not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_session_acl_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tenant_id, session_id, principal_type, principal_id, access_level,
                      granted_by::text, created_at::text
               FROM chat_session_acl
               WHERE tenant_id=%s AND session_id=%s
               ORDER BY created_at""",
            (tid, sid),
        )
        rows = cur.fetchall()
    return [
        {
            "tenant_id": str(r[0]),
            "session_id": str(r[1]),
            "principal_type": str(r[2]),
            "principal_id": str(r[3]),
            "access_level": str(r[4]),
            "granted_by": str(r[5]) if r[5] else None,
            "created_at": str(r[6] or ""),
        }
        for r in rows
    ]


def upsert_session_acl(
    *,
    session_id: str,
    principal_type: str,
    principal_id: str,
    access_level: str = "read",
    tenant_id: str | None = None,
    granted_by: str | None = None,
) -> dict[str, Any]:
    sid = (session_id or "").strip()
    ptype = (principal_type or "").strip().lower()
    pid = (principal_id or "").strip()
    level = (access_level or "read").strip().lower()
    if not sid:
        raise ValueError("invalid_session_id")
    if ptype not in VALID_PRINCIPAL_TYPES:
        raise ValueError("invalid_principal_type")
    if not pid:
        raise ValueError("invalid_principal_id")
    if level not in VALID_ACCESS_LEVELS:
        raise ValueError("invalid_access_level")
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    grantor = _user_uuid(granted_by or get_current_sub())
    ensure_session_acl_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO chat_session_acl
               (tenant_id, session_id, principal_type, principal_id, access_level, granted_by)
               VALUES (%s,%s,%s,%s,%s,%s::uuid)
               ON CONFLICT (tenant_id, session_id, principal_type, principal_id)
               DO UPDATE SET access_level=EXCLUDED.access_level, granted_by=EXCLUDED.granted_by
               RETURNING tenant_id, session_id, principal_type, principal_id, access_level,
                         granted_by::text, created_at::text""",
            (tid, sid, ptype, pid, level, grantor),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("acl_upsert_failed")
    return {
        "tenant_id": str(row[0]),
        "session_id": str(row[1]),
        "principal_type": str(row[2]),
        "principal_id": str(row[3]),
        "access_level": str(row[4]),
        "granted_by": str(row[5]) if row[5] else None,
        "created_at": str(row[6] or ""),
    }


def delete_session_acl(
    *,
    session_id: str,
    principal_type: str,
    principal_id: str,
    tenant_id: str | None = None,
) -> bool:
    sid = (session_id or "").strip()
    ptype = (principal_type or "").strip().lower()
    pid = (principal_id or "").strip()
    if not sid or ptype not in VALID_PRINCIPAL_TYPES or not pid:
        raise ValueError("invalid_acl_principal")
    if not memory_db_enabled():
        return False
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_session_acl_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM chat_session_acl
               WHERE tenant_id=%s AND session_id=%s AND principal_type=%s AND principal_id=%s
               RETURNING session_id""",
            (tid, sid, ptype, pid),
        )
        return cur.fetchone() is not None


def user_can_access_session(
    *,
    session_id: str,
    role: str | None,
    user_id: str | None,
    tenant_id: str | None = None,
) -> bool:
    if role in ("admin", "lead", "auditor"):
        return True
    uid = _user_uuid(user_id)
    normalized_role = (role or "").strip().lower()
    entries = list_session_acl(session_id=session_id, tenant_id=tenant_id)
    for entry in entries:
        if entry["principal_type"] == "user" and uid and entry["principal_id"] == uid:
            return True
        if entry["principal_type"] == "role" and normalized_role and entry["principal_id"] == normalized_role:
            return True
    return False
