"""H1 — Work queue (team work items)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.audit_service import append_audit_event
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)

router_work_queue = APIRouter()

VALID_STATUS = frozenset({"open", "in_progress", "review", "done", "cancelled"})
VALID_PRIORITY = frozenset({"low", "normal", "high", "urgent"})
VALID_SOURCE = frozenset({"manual", "agent", "rejection", "ci", "policy", "tool_failure"})
WORK_ITEM_MUTATION_ROLES = ("developer", "reviewer", "lead", "approver", "admin")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_uuid(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def ensure_work_items_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS work_item_counters (
                tenant_id TEXT PRIMARY KEY, next_seq INT NOT NULL DEFAULT 1
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS work_items (
                id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'review', 'done', 'cancelled')),
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                assignee_id UUID,
                reporter_id UUID NOT NULL,
                workspace_path TEXT,
                repo TEXT,
                session_id TEXT,
                approval_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                labels TEXT[] NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('manual', 'agent', 'rejection', 'ci', 'policy', 'tool_failure')),
                agent_name TEXT,
                skills TEXT[] NOT NULL DEFAULT '{}',
                context_links TEXT[] NOT NULL DEFAULT '{}',
                blocked_by TEXT[] NOT NULL DEFAULT '{}',
                reviewer_id UUID,
                required_approvals INT NOT NULL DEFAULT 1,
                attached_artifacts JSONB NOT NULL DEFAULT '{}'::jsonb,
                sort_order INT NOT NULL DEFAULT 0,
                external_url TEXT,
                external_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                closed_at TIMESTAMPTZ,
                PRIMARY KEY (tenant_id, id)
            );"""
        )
        cur.execute(
            """DO $$
               DECLARE
                   pk_name TEXT;
               BEGIN
                   SELECT conname INTO pk_name
                   FROM pg_constraint
                   WHERE conrelid = 'work_items'::regclass
                     AND contype = 'p';

                   IF pk_name IS NOT NULL AND pk_name <> 'work_items_tenant_id_id_pkey' THEN
                       EXECUTE format('ALTER TABLE work_items DROP CONSTRAINT %I', pk_name);
                   END IF;

                   IF NOT EXISTS (
                       SELECT 1 FROM pg_constraint
                       WHERE conrelid = 'work_items'::regclass
                         AND conname = 'work_items_tenant_id_id_pkey'
                   ) THEN
                       ALTER TABLE work_items
                           ADD CONSTRAINT work_items_tenant_id_id_pkey PRIMARY KEY (tenant_id, id);
                   END IF;
               END $$;"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS work_items_tenant_status_idx ON work_items (tenant_id, status, updated_at DESC);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS work_items_tenant_assignee_status_idx "
            "ON work_items (tenant_id, assignee_id, status, updated_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS work_items_tenant_session_idx "
            "ON work_items (tenant_id, session_id) WHERE session_id IS NOT NULL;"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS work_items_approval_ids_gin_idx ON work_items USING GIN (approval_ids);")
        # ── Bloco A: agent/skills/context columns (idempotent migration) ──
        for col, col_type in [
            ("agent_name", "TEXT"),
            ("skills", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("context_links", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("blocked_by", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("reviewer_id", "UUID"),
            ("required_approvals", "INT NOT NULL DEFAULT 1"),
            ("attached_artifacts", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
            ("due_date", "DATE"),
            ("estimated_hours", "FLOAT"),
            ("sprint_id", "TEXT"),
            ("story_points", "INT DEFAULT 1"),
        ]:
            cur.execute(
                f"""DO $$
                   BEGIN
                       IF NOT EXISTS (
                           SELECT 1 FROM information_schema.columns
                           WHERE table_name='work_items' AND column_name='{col}'
                       ) THEN
                           ALTER TABLE work_items ADD COLUMN {col} {col_type};
                       END IF;
                   END $$;"""
            )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS work_item_events (
                event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL,
                actor_id UUID,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY (tenant_id, work_item_id) REFERENCES work_items (tenant_id, id) ON DELETE CASCADE
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS work_item_events_tenant_item_created_idx "
            "ON work_item_events (tenant_id, work_item_id, created_at DESC);"
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS work_item_comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL,
                author_id UUID NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY (tenant_id, work_item_id) REFERENCES work_items (tenant_id, id) ON DELETE CASCADE
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS work_item_comments_tenant_item_created_idx "
            "ON work_item_comments (tenant_id, work_item_id, created_at);"
        )
        cur.execute("ALTER TABLE work_item_counters ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE work_items ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE work_item_events ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE work_item_comments ENABLE ROW LEVEL SECURITY;")
        cur.execute("DROP POLICY IF EXISTS work_item_counters_tenant_rls ON work_item_counters;")
        cur.execute(
            """CREATE POLICY work_item_counters_tenant_rls ON work_item_counters
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )
        cur.execute("DROP POLICY IF EXISTS work_items_tenant_rls ON work_items;")
        cur.execute(
            """CREATE POLICY work_items_tenant_rls ON work_items
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )
        cur.execute("DROP POLICY IF EXISTS work_item_events_tenant_rls ON work_item_events;")
        cur.execute(
            """CREATE POLICY work_item_events_tenant_rls ON work_item_events
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )
        cur.execute("DROP POLICY IF EXISTS work_item_comments_tenant_rls ON work_item_comments;")
        cur.execute(
            """CREATE POLICY work_item_comments_tenant_rls ON work_item_comments
               USING (tenant_id = current_setting('app.tenant_id', true))
               WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
        )


def list_work_item_events(item_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    wid = (item_id or "").strip()
    if not wid or not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT event_id::text, tenant_id, work_item_id, actor_id::text, event_type,
                      from_status, to_status, metadata, created_at::text
               FROM work_item_events
               WHERE tenant_id=%s AND work_item_id=%s
               ORDER BY created_at""",
            (tid, wid),
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row[7]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        out.append(
            {
                "event_id": str(row[0]),
                "tenant_id": str(row[1]),
                "work_item_id": str(row[2]),
                "actor_id": str(row[3]) if row[3] else None,
                "event_type": str(row[4]),
                "from_status": row[5],
                "to_status": row[6],
                "metadata": meta if isinstance(meta, dict) else {},
                "created_at": str(row[8] or ""),
            }
        )
    return out


def list_work_item_comments(item_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    wid = (item_id or "").strip()
    if not wid or not memory_db_enabled():
        return []
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, work_item_id, author_id::text, body, created_at::text
               FROM work_item_comments
               WHERE tenant_id=%s AND work_item_id=%s
               ORDER BY created_at""",
            (tid, wid),
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]),
            "work_item_id": str(r[2]),
            "author_id": str(r[3]),
            "body": str(r[4]),
            "created_at": str(r[5] or ""),
        }
        for r in rows
    ]


def add_work_item_comment(
    item_id: str,
    *,
    body: str,
    author_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    wid = (item_id or "").strip()
    text = (body or "").strip()
    if not wid or not text:
        raise ValueError("empty_comment")
    author = _user_uuid(author_id or get_current_sub())
    if not author:
        raise ValueError("author_required")
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not get_work_item(wid, tenant_id=tid):
        raise ValueError("work_item_not_found")
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO work_item_comments (tenant_id, work_item_id, author_id, body)
               VALUES (%s,%s,%s::uuid,%s)
               RETURNING id::text, tenant_id, work_item_id, author_id::text, body, created_at::text""",
            (tid, wid, author, text[:4000]),
        )
        row = cur.fetchone()
    _record_work_item_event(
        tenant_id=tid,
        work_item_id=wid,
        event_type="comment_added",
        actor_id=author,
        metadata={"comment_id": str(row[0])},
    )
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "work_item_id": str(row[2]),
        "author_id": str(row[3]),
        "body": str(row[4]),
        "created_at": str(row[5] or ""),
    }


def _next_work_item_id(*, tenant_id: str) -> str:
    ensure_work_items_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO work_item_counters (tenant_id, next_seq)
               VALUES (%s, 2) ON CONFLICT (tenant_id) DO UPDATE
               SET next_seq = work_item_counters.next_seq + 1
               RETURNING next_seq - 1""",
            (tenant_id,),
        )
        row = cur.fetchone()
        seq = int(row[0]) if row else 1
    return f"WI-{seq}"


def _record_work_item_event(
    *,
    tenant_id: str,
    work_item_id: str,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a collaboration event. Best-effort so workflow mutations stay available."""
    if not memory_db_enabled():
        return
    tid = (tenant_id or "").strip() or "default"
    wid = (work_item_id or "").strip()
    ev = (event_type or "").strip()
    if not wid or not ev:
        return
    actor = _user_uuid(actor_id or get_current_sub())
    try:
        ensure_work_items_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO work_item_events
                   (tenant_id, work_item_id, actor_id, event_type, from_status, to_status, metadata)
                   VALUES (%s,%s,%s::uuid,%s,%s,%s,%s::jsonb)""",
                (
                    tid,
                    wid,
                    actor,
                    ev[:120],
                    from_status,
                    to_status,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
    except Exception:
        logger.debug("record work item event failed item=%s event=%s", wid, ev, exc_info=True)


def _row_to_item(r: tuple[Any, ...]) -> dict[str, Any]:
    approvals = r[11]
    if isinstance(approvals, str):
        try:
            approvals = json.loads(approvals)
        except json.JSONDecodeError:
            approvals = []
    labels = list(r[12] or [])
    return {
        "id": str(r[0]),
        "tenant_id": str(r[1]),
        "title": str(r[2]),
        "description": str(r[3] or ""),
        "status": str(r[4]),
        "priority": str(r[5]),
        "assignee_id": str(r[6]) if r[6] else None,
        "reporter_id": str(r[7]) if r[7] else None,
        "workspace_path": r[8],
        "repo": r[9],
        "session_id": r[10],
        "approval_ids": approvals if isinstance(approvals, list) else [],
        "labels": [str(x) for x in labels],
        "source": str(r[13]),
        "agent_name": str(r[14]) if r[14] else None,
        "skills": [str(x) for x in (list(r[15] or []))],
        "context_links": [str(x) for x in (list(r[16] or []))],
        "blocked_by": [str(x) for x in (list(r[17] or []))],
        "reviewer_id": str(r[18]) if r[18] else None,
        "required_approvals": int(r[19] or 1),
        "attached_artifacts": r[20] if isinstance(r[20], dict) else {},
        "external_url": r[21],
        "external_id": r[22],
        "created_at": str(r[23] or ""),
        "updated_at": str(r[24] or ""),
        "closed_at": str(r[25] or "") if r[25] else None,
    }


def create_work_item(
    *,
    title: str,
    description: str | None = None,
    priority: str = "normal",
    labels: list[str] | None = None,
    source: str = "manual",
    workspace_path: str | None = None,
    session_id: str | None = None,
    approval_ids: list[str] | None = None,
    reporter_id: str | None = None,
    tenant_id: str | None = None,
    agent_name: str | None = None,
    skills: list[str] | None = None,
    context_links: list[str] | None = None,
    blocked_by: list[str] | None = None,
    reviewer_id: str | None = None,
    required_approvals: int = 1,
    attached_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    t = (title or "").strip()
    if len(t) < 1:
        raise ValueError("empty_title")
    pr = priority if priority in VALID_PRIORITY else "normal"
    src = source if source in VALID_SOURCE else "manual"
    rep = _user_uuid(reporter_id or get_current_sub())
    if not rep:
        raise ValueError("reporter_required")
    wid = _next_work_item_id(tenant_id=tid)
    now = _utc_iso()
    lbl = [str(x)[:64] for x in (labels or [])[:20]]
    aids = [str(x).strip() for x in (approval_ids or []) if str(x).strip()][:20]
    sk = [str(x)[:64] for x in (skills or [])[:20]]
    cl = [str(x)[:500] for x in (context_links or [])[:20]]
    ag = (agent_name or "").strip()[:100] or None
    bl = [str(x).strip() for x in (blocked_by or []) if str(x).strip()][:20]
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO work_items
               (id, tenant_id, title, description, status, priority, reporter_id,
                workspace_path, session_id, approval_ids, labels, source,
                agent_name, skills, context_links, blocked_by, created_at, updated_at)
               VALUES (%s,%s,%s,%s,'open',%s,%s::uuid,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                wid,
                tid,
                t,
                (description or "")[:4000],
                pr,
                rep,
                workspace_path,
                session_id,
                json.dumps(aids),
                lbl,
                src,
                ag,
                sk,
                cl,
                bl,
                now,
                now,
            ),
        )
    _record_work_item_event(
        tenant_id=tid,
        work_item_id=wid,
        event_type="created",
        to_status="open",
        actor_id=rep,
        metadata={"source": src, "priority": pr},
    )
    append_audit_event(action="work_item.created", tenant_id=tid, user_id=rep, work_item_id=wid, resource=t)
    return get_work_item(wid, tenant_id=tid) or {"id": wid, "title": t}


def get_work_item(item_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, title, description, status, priority, assignee_id, reporter_id,
                   workspace_path, repo, session_id, approval_ids, labels, source, agent_name, skills,
                   context_links, blocked_by, reviewer_id, required_approvals, attached_artifacts, external_url, external_id,
                   created_at, updated_at, closed_at
               FROM work_items WHERE tenant_id=%s AND id=%s LIMIT 1""",
            (tid, item_id),
        )
        row = cur.fetchone()
    return _row_to_item(row) if row else None


def list_work_items(
    *,
    tenant_id: str | None = None,
    status: str | None = None,
    assignee_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    clauses = ["tenant_id=%s"]
    params: list[Any] = [tid]
    if status and status in VALID_STATUS:
        clauses.append("status=%s")
        params.append(status)
    if assignee_id:
        uid = _user_uuid(assignee_id)
        if uid:
            clauses.append("assignee_id=%s::uuid")
            params.append(uid)
    params.append(max(1, min(500, int(limit))))
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, tenant_id, title, description, status, priority, assignee_id, reporter_id,
                   workspace_path, repo, session_id, approval_ids, labels, source, agent_name, skills,
                   context_links, blocked_by, reviewer_id, required_approvals, attached_artifacts, external_url, external_id,
                   created_at, updated_at, closed_at
                FROM work_items WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC LIMIT %s""",
            params,
        )
        return [_row_to_item(r) for r in cur.fetchall()]


def patch_work_item(
    item_id: str,
    *,
    status: str | None = None,
    assignee_id: str | None = None,
    title: str | None = None,
    session_id: str | None = None,
    priority: str | None = None,
    agent_name: str | None = None,
    skills: list[str] | None = None,
    context_links: list[str] | None = None,
    blocked_by: list[str] | None = None,
    reviewer_id: str | None = None,
    required_approvals: int | None = None,
    attached_artifacts: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    before = get_work_item(item_id, tenant_id=tid)
    fields: list[tuple[str, Any]] = []
    if status and status in VALID_STATUS:
        fields.append(("status", status))
    if assignee_id is not None:
        fields.append(("assignee_id", _user_uuid(assignee_id)))
    if title is not None:
        t = title.strip()
        if t:
            fields.append(("title", t))
    if session_id is not None:
        fields.append(("session_id", session_id.strip() or None))
    if priority and priority in VALID_PRIORITY:
        fields.append(("priority", priority))
    if agent_name is not None:
        fields.append(("agent_name", agent_name.strip()[:100] or None))
    if skills is not None:
        fields.append(("skills", [str(x)[:64] for x in skills[:20]]))
    if context_links is not None:
        fields.append(("context_links", [str(x)[:500] for x in context_links[:20]]))
    if blocked_by is not None:
        fields.append(("blocked_by", [str(x).strip() for x in blocked_by[:20] if str(x).strip()]))
    if not fields:
        return before or get_work_item(item_id, tenant_id=tid)
    now = _utc_iso()
    fields.append(("updated_at", now))
    if status == "done":
        fields.append(("closed_at", now))
    set_sql = ", ".join(f"{k}=%s" for k, _ in fields)
    vals = [v for _, v in fields] + [tid, item_id]
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE work_items SET {set_sql} WHERE tenant_id=%s AND id=%s RETURNING id",
            vals,
        )
        if not cur.fetchone():
            return None
    after = get_work_item(item_id, tenant_id=tid)
    if after:
        prev_status = str(before.get("status")) if before else None
        next_status = str(after.get("status") or "")
        event_type = "status_changed" if status and prev_status != next_status else "updated"
        _record_work_item_event(
            tenant_id=tid,
            work_item_id=item_id,
            event_type=event_type,
            from_status=prev_status if event_type == "status_changed" else None,
            to_status=next_status if event_type == "status_changed" else None,
            metadata={
                "title_changed": title is not None,
                "assignee_changed": assignee_id is not None,
                "session_changed": session_id is not None,
                "priority_changed": priority is not None,
            },
        )
    if status == "done":
        append_audit_event(action="work_item.closed", tenant_id=tid, work_item_id=item_id)
    return after


def find_work_item_by_approval(
    approval_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Return work item that already references this approval (reopen instead of duplicate)."""
    aid = (approval_id or "").strip()
    if not aid or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, title, description, status, priority, assignee_id, reporter_id,
                   workspace_path, repo, session_id, approval_ids, labels, source, agent_name, skills,
                   context_links, blocked_by, reviewer_id, required_approvals, attached_artifacts, external_url, external_id,
                   created_at, updated_at, closed_at
               FROM work_items
               WHERE tenant_id=%s AND approval_ids @> %s::jsonb
               ORDER BY updated_at DESC LIMIT 1""",
            (tid, json.dumps([aid])),
        )
        row = cur.fetchone()
    return _row_to_item(row) if row else None


def _denial_work_item_title(rec: dict[str, Any], reason: str) -> str:
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    path = str(payload.get("path") or payload.get("file") or "").strip()
    action_id = str(rec.get("action_id") or "approval").strip()
    if path:
        return f"Follow-up: {action_id} — {path}"[:500]
    if reason.strip():
        r = reason.strip()
        return (f"Follow-up: {r[:120]}" if len(r) > 120 else f"Follow-up: {r}")[:500]
    return f"Follow-up: {action_id} denied"[:500]


def maybe_create_work_item_from_denial(
    *,
    approval_id: str,
    approval_rec: dict[str, Any],
    reason: str = "",
    tenant_id: str | None = None,
    reporter_id: str | None = None,
) -> dict[str, Any] | None:
    """H1b — auto WI on approval.denied (creates or reopens linked item)."""
    if not memory_db_enabled():
        return None
    aid = (approval_id or "").strip()
    if not aid:
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    rep = _user_uuid(reporter_id or get_current_sub())
    if not rep:
        logger.debug("skip work_item from denial: no reporter")
        return None

    existing = find_work_item_by_approval(aid, tenant_id=tid)
    sid = str(approval_rec.get("session_id") or "").strip() or None
    if existing:
        wid = str(existing.get("id") or "")
        if existing.get("status") in ("done", "cancelled"):
            patch_work_item(wid, status="open", session_id=sid or existing.get("session_id"), tenant_id=tid)
        elif sid and not existing.get("session_id"):
            patch_work_item(wid, session_id=sid, tenant_id=tid)
        item = get_work_item(wid, tenant_id=tid) or existing
        append_audit_event(
            action="work_item.reopened",
            tenant_id=tid,
            user_id=rep,
            work_item_id=wid,
            approval_id=aid,
            session_id=sid,
            metadata={"source": "approval.denied", "reason": reason[:500] if reason else None},
        )
        return item

    title = _denial_work_item_title(approval_rec, reason)
    desc_parts = []
    if reason.strip():
        desc_parts.append(f"Motivo da rejeição: {reason.strip()}")
    action_id = str(approval_rec.get("action_id") or "")
    if action_id:
        desc_parts.append(f"action_id: {action_id}")
    payload = approval_rec.get("payload")
    if isinstance(payload, dict) and payload:
        try:
            desc_parts.append("payload: " + json.dumps(payload, ensure_ascii=False)[:1500])
        except TypeError:
            pass
    description = "\n".join(desc_parts)[:4000] or None
    labels = ["rejection"]
    if action_id:
        labels.append(action_id[:64])

    try:
        item = create_work_item(
            title=title,
            description=description,
            priority="normal",
            labels=labels,
            source="rejection",
            session_id=sid,
            approval_ids=[aid],
            reporter_id=rep,
            tenant_id=tid,
        )
    except (RuntimeError, ValueError) as exc:
        logger.debug("work_item from denial failed: %s", exc)
        return None

    wid = str(item.get("id") or "")
    append_audit_event(
        action="approval.denied",
        tenant_id=tid,
        user_id=rep,
        work_item_id=wid,
        approval_id=aid,
        session_id=sid,
        resource=action_id or aid,
        metadata={"reason": reason[:500] if reason else None, "auto_work_item": True},
    )
    return item


def patch_work_item_external(
    item_id: str,
    *,
    external_url: str | None = None,
    external_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """H2 — link work item to Linear/Jira/GitHub issue."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    ensure_work_items_schema()
    now = _utc_iso()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE work_items SET external_url=%s, external_id=%s, updated_at=%s
               WHERE tenant_id=%s AND id=%s RETURNING id""",
            (external_url, external_id, now, tid, item_id),
        )
        if not cur.fetchone():
            return None
    _record_work_item_event(
        tenant_id=tid,
        work_item_id=item_id,
        event_type="external_linked",
        metadata={"external_url": external_url, "external_id": external_id},
    )
    append_audit_event(
        action="work_item.linked",
        tenant_id=tid,
        work_item_id=item_id,
        resource=external_url,
        metadata={"external_id": external_id},
    )
    return get_work_item(item_id, tenant_id=tid)


class WorkItemCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="normal")
    labels: list[str] = Field(default_factory=list)
    workspace_path: str | None = None
    session_id: str | None = None
    agent_name: str | None = Field(default=None, max_length=100, description="Agent to use (coder, reviewer, architect)")
    skills: list[str] = Field(default_factory=list, description="Skills to inject as L3 context")
    context_links: list[str] = Field(default_factory=list, description="URLs of docs/KB articles for context")
    blocked_by: list[str] = Field(default_factory=list, description="WI IDs that block this one")
    watchers: list[str] = Field(default_factory=list, description="User IDs to notify on status changes")
    reviewer_id: str | None = Field(default=None, description="Reviewer UUID")
    due_date: str | None = Field(default=None, description="Deadline (ISO date)")
    estimated_hours: float | None = Field(default=None, ge=0)
    sprint_id: str | None = Field(default=None, max_length=100)
    story_points: int = Field(default=1, ge=1, le=100)
    required_approvals: int = Field(default=1, ge=1, le=10, description="Approvals needed for done")


class WorkItemPatchBody(BaseModel):
    status: str | None = None
    assignee_id: str | None = None
    title: str | None = None
    session_id: str | None = None
    priority: str | None = None
    agent_name: str | None = Field(default=None, max_length=100)
    skills: list[str] | None = None
    context_links: list[str] | None = None
    blocked_by: list[str] | None = Field(default=None, description="WI IDs that block this one")
    reviewer_id: str | None = None
    required_approvals: int | None = None
    attached_artifacts: dict[str, Any] | None = Field(default=None, description="Diffs, PRs, test reports")
    due_date: str | None = None
    estimated_hours: float | None = None
    sprint_id: str | None = None
    story_points: int | None = None
    external_url: str | None = None
    external_id: str | None = None


class WorkItemCommentBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class WorkItemLinkBody(BaseModel):
    external_url: str = Field(..., min_length=8, max_length=2000)
    external_id: str | None = Field(default=None, max_length=256)


@router_work_queue.get("/ui/work-items", tags=["WidgetMVP"])
def ui_work_items_list(
    status: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if not memory_db_enabled():
        return {"items": [], "work_items_enabled": False}
    items = list_work_items(status=status, assignee_id=assignee_id)
    return {"items": items, "work_items_enabled": True}


@router_work_queue.post("/ui/work-items", tags=["WidgetMVP"])
def ui_work_items_create(body: WorkItemCreateBody) -> dict[str, Any]:
    from app.shared.rbac import require_any_role

    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        item = create_work_item(
            title=body.title,
            description=body.description,
            priority=body.priority,
            labels=body.labels,
            workspace_path=body.workspace_path,
            session_id=body.session_id,
            agent_name=body.agent_name,
            skills=body.skills,
            context_links=body.context_links,
            blocked_by=body.blocked_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item}


@router_work_queue.get("/ui/work-items/{item_id}", tags=["WidgetMVP"])
def ui_work_items_get(item_id: str) -> dict[str, Any]:
    item = get_work_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")
    return {"item": item}


@router_work_queue.patch("/ui/work-items/{item_id}", tags=["WidgetMVP"])
def ui_work_items_patch(item_id: str, body: WorkItemPatchBody) -> dict[str, Any]:
    from app.shared.rbac import get_current_role, require_any_role

    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    role = get_current_role()
    if role == "viewer":
        raise HTTPException(status_code=403, detail="viewer_read_only")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    # C3: Status propagation — blocked WI cannot move to in_progress
    if body.status == "in_progress":
        item = get_work_item(item_id)
        blockers = item.get("blocked_by", []) if item else []
        if blockers:
            still_blocked = []
            for bid in blockers:
                b = get_work_item(bid)
                if b and b.get("status") not in ("done", "cancelled"):
                    still_blocked.append(bid)
            if still_blocked:
                raise HTTPException(
                    status_code=409,
                    detail=f"blocked_by_{','.join(still_blocked)}",
                )
    item = patch_work_item(
        item_id,
        status=body.status,
        assignee_id=body.assignee_id,
        title=body.title,
        session_id=body.session_id,
        priority=body.priority,
        agent_name=body.agent_name,
        skills=body.skills,
        context_links=body.context_links,
        blocked_by=body.blocked_by,
    )
    if not item:
        raise HTTPException(status_code=404, detail="not_found")
    # F3: fire webhooks on status change
    if body.status and item.get("status") == body.status:
        _fire_webhooks(item, f"status_{body.status}", "default")
    if body.external_url or body.external_id:
        item = patch_work_item_external(
            item_id,
            external_url=body.external_url,
            external_id=body.external_id,
        ) or item
    return {"item": item}


@router_work_queue.get("/ui/work-items/{item_id}/events", tags=["WidgetMVP"])
def ui_work_items_events(item_id: str) -> dict[str, Any]:
    from app.shared.rbac import require_any_role

    require_any_role("viewer", "developer", "reviewer", "lead", "approver", "auditor", "admin")
    if not memory_db_enabled():
        return {"items": [], "work_items_enabled": False}
    if not get_work_item(item_id):
        raise HTTPException(status_code=404, detail="not_found")
    return {"items": list_work_item_events(item_id), "work_items_enabled": True}


@router_work_queue.get("/ui/work-items/{item_id}/comments", tags=["WidgetMVP"])
def ui_work_items_comments_list(item_id: str) -> dict[str, Any]:
    from app.shared.rbac import require_any_role

    require_any_role("viewer", "developer", "reviewer", "lead", "approver", "auditor", "admin")
    if not memory_db_enabled():
        return {"items": [], "work_items_enabled": False}
    if not get_work_item(item_id):
        raise HTTPException(status_code=404, detail="not_found")
    return {"items": list_work_item_comments(item_id), "work_items_enabled": True}


@router_work_queue.post("/ui/work-items/{item_id}/comments", tags=["WidgetMVP"])
def ui_work_items_comments_create(item_id: str, body: WorkItemCommentBody) -> dict[str, Any]:
    from app.shared.rbac import get_current_role, require_any_role

    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    role = get_current_role()
    if role == "viewer":
        raise HTTPException(status_code=403, detail="viewer_read_only")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        comment = add_work_item_comment(item_id, body=body.body)
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "work_item_not_found" else 422
        raise HTTPException(status_code=status, detail=code) from exc
    return {"comment": comment, "ok": True}


@router_work_queue.post("/ui/work-items/{item_id}/link", tags=["WidgetMVP"])
def ui_work_items_link(item_id: str, body: WorkItemLinkBody) -> dict[str, Any]:
    """H2 — attach Linear/Jira/GitHub issue URL."""
    from app.shared.rbac import require_any_role

    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    item = patch_work_item_external(
        item_id,
        external_url=body.external_url,
        external_id=body.external_id,
    )
    if not item:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "item": item}


@router_work_queue.get("/ui/work-items/{item_id}/blocked-by", tags=["WidgetMVP"])
def ui_work_items_blocked_by(item_id: str) -> dict[str, Any]:
    """C3 — Return list of blockers with status, showing why this WI can't progress."""
    item = get_work_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")
    blockers = item.get("blocked_by", [])
    resolved: list[dict[str, Any]] = []
    for bid in blockers:
        b = get_work_item(bid)
        resolved.append({
            "id": bid,
            "title": b["title"] if b else "(not found)",
            "status": b["status"] if b else "unknown",
            "blocking": b["status"] not in ("done", "cancelled") if b else False,
        })
    return {"item_id": item_id, "blockers": resolved, "is_blocked": any(r["blocking"] for r in resolved)}


@router_work_queue.post("/ui/work-items/{item_id}/work", tags=["WidgetMVP"])
def ui_work_items_work(item_id: str) -> dict[str, Any]:
    """Mark in_progress and return session hint for CLI `central queue work`."""
    from app.shared.rbac import require_any_role

    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    existing = get_work_item(item_id)
    if not existing:
        raise HTTPException(status_code=404, detail="not_found")
    sid = existing.get("session_id")
    if not sid:
        from app.sessions import create_session

        sess = create_session(title=existing.get("title"))
        sid = str(sess.get("id") or "")
        patch_work_item(item_id, status="in_progress", session_id=sid)
        existing = get_work_item(item_id) or existing
    else:
        patch_work_item(item_id, status="in_progress")
        existing = get_work_item(item_id) or existing
    return {
        "ok": True,
        "item": existing,
        "session_id": sid,
        "hint": f"central open \"{existing.get('title', item_id)}\"",
    }


# ═══════════════════════════════════════════════════════════════
# Bloco D — WI Templates
# ═══════════════════════════════════════════════════════════════

def _ensure_templates_schema(cur: Any) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS wi_templates (
            id TEXT NOT NULL, tenant_id TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT, agent_name TEXT,
            skills TEXT[] NOT NULL DEFAULT '{}',
            labels TEXT[] NOT NULL DEFAULT '{}',
            priority TEXT NOT NULL DEFAULT 'normal',
            workspace_path TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id)
        );"""
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS wi_templates_tenant_idx "
        "ON wi_templates (tenant_id, name);"
    )


class TemplateCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    agent_name: str | None = None
    skills: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    priority: str = Field(default="normal")
    workspace_path: str | None = None


def list_templates(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        _ensure_templates_schema(cur)
        cur.execute(
            """SELECT id, tenant_id, name, description, agent_name, skills, labels,
                      priority, workspace_path, created_at, updated_at
               FROM wi_templates WHERE tenant_id=%s ORDER BY name""",
            (tid,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "tenant_id": r[1], "name": r[2], "description": r[3],
         "agent_name": r[4], "skills": list(r[5] or []), "labels": list(r[6] or []),
         "priority": r[7], "workspace_path": r[8],
         "created_at": str(r[9]), "updated_at": str(r[10])}
        for r in rows
    ]


def create_template(
    *,
    name: str,
    description: str | None = None,
    agent_name: str | None = None,
    skills: list[str] | None = None,
    labels: list[str] | None = None,
    priority: str = "normal",
    workspace_path: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    import uuid as _uuid
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    tname = (name or "").strip()
    if not tname:
        raise ValueError("empty_name")
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    ensure_work_items_schema()
    tid2 = str(_uuid.uuid4())[:8]
    now = _utc_iso()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        _ensure_templates_schema(cur)
        cur.execute(
            """INSERT INTO wi_templates (id, tenant_id, name, description, agent_name,
               skills, labels, priority, workspace_path, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (tid2, tid, tname, description, agent_name,
             skills or [], labels or [], priority, workspace_path, now, now),
        )
    return {"id": tid2, "name": tname, "tenant_id": tid}


def get_template(template_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    ensure_work_items_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        _ensure_templates_schema(cur)
        cur.execute(
            """SELECT id, tenant_id, name, description, agent_name, skills, labels,
                      priority, workspace_path, created_at, updated_at
               FROM wi_templates WHERE tenant_id=%s AND id=%s""",
            (tid, template_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "tenant_id": row[1], "name": row[2], "description": row[3],
            "agent_name": row[4], "skills": list(row[5] or []), "labels": list(row[6] or []),
            "priority": row[7], "workspace_path": row[8],
            "created_at": str(row[9]), "updated_at": str(row[10])}


@router_work_queue.get("/ui/work-items/templates", tags=["WidgetMVP"])
def ui_templates_list() -> dict[str, Any]:
    return {"items": list_templates()}


@router_work_queue.post("/ui/work-items/templates", tags=["WidgetMVP"])
def ui_templates_create(body: TemplateCreateBody) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        tpl = create_template(
            name=body.name, description=body.description,
            agent_name=body.agent_name, skills=body.skills,
            labels=body.labels, priority=body.priority,
            workspace_path=body.workspace_path,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"template": tpl}


@router_work_queue.post("/ui/work-items/from-template/{template_id}", tags=["WidgetMVP"])
def ui_work_items_from_template(template_id: str) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    tpl = get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="template_not_found")
    try:
        item = create_work_item(
            title=tpl["name"],
            description=tpl.get("description"),
            priority=tpl.get("priority", "normal"),
            labels=tpl.get("labels", []),
            agent_name=tpl.get("agent_name"),
            skills=tpl.get("skills", []),
            workspace_path=tpl.get("workspace_path"),
            source="manual",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"item": item, "template_id": template_id}


# ═══════════════════════════════════════════════════════════════
# Bloco E — Review endpoint + auto-transition
# ═══════════════════════════════════════════════════════════════

@router_work_queue.post("/ui/work-items/{item_id}/review", tags=["WidgetMVP"])
def ui_work_items_review(item_id: str) -> dict[str, Any]:
    """E5 — Transition to review and notify reviewer."""
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    item = get_work_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")
    if item.get("status") not in ("in_progress", "open"):
        raise HTTPException(status_code=409, detail=f"cannot_review_from_{item.get('status')}")
    reviewer = item.get("reviewer_id")
    if not reviewer:
        raise HTTPException(status_code=400, detail="no_reviewer_assigned")
    updated = patch_work_item(item_id, status="review")
    return {"ok": True, "item": updated, "reviewer_id": reviewer}


def _check_auto_transition(item_id: str, tenant_id: str = "default") -> None:
    """E4 — Auto-transition review→done when approvals >= required."""
    item = get_work_item(item_id, tenant_id=tenant_id)
    if not item or item.get("status") != "review":
        return
    required = int(item.get("required_approvals", 1))
    approval_ids = item.get("approval_ids", [])
    if len(approval_ids) < required:
        return
    # Check how many are approved
    from app.shared.approvals_store import get_approval
    approved = 0
    for aid in approval_ids:
        rec = get_approval(aid, tenant_id=tenant_id)
        if rec and rec.get("status") == "approved":
            approved += 1
    if approved >= required:
        patch_work_item(item_id, status="done", tenant_id=tenant_id)
        logger.info("auto_transition WI %s → done (%d/%d approvals)", item_id, approved, required)


def add_watcher(item_id: str, user_id: str, *, tenant_id: str | None = None) -> bool:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled(): return False
    uid = _user_uuid(user_id)
    if not uid: return False
    ensure_work_items_schema()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO wi_watchers (tenant_id, work_item_id, user_id) VALUES (%s,%s,%s::uuid) ON CONFLICT DO NOTHING", (tid, item_id, uid))
        return True
    except Exception: return False


def remove_watcher(item_id: str, user_id: str, *, tenant_id: str | None = None) -> bool:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    uid = _user_uuid(user_id)
    if not uid or not memory_db_enabled(): return False
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM wi_watchers WHERE tenant_id=%s AND work_item_id=%s AND user_id=%s::uuid", (tid, item_id, uid))
        return True
    except Exception: return False


def list_watchers(item_id: str, *, tenant_id: str | None = None) -> list[str]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled(): return []
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id::text FROM wi_watchers WHERE tenant_id=%s AND work_item_id=%s", (tid, item_id))
            return [r[0] for r in cur.fetchall()]
    except Exception: return []


@router_work_queue.post("/ui/work-items/{item_id}/watchers", tags=["WidgetMVP"])
def ui_watchers_add(item_id: str, user_id: str = Query(...)) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not get_work_item(item_id): raise HTTPException(status_code=404, detail="not_found")
    ok = add_watcher(item_id, user_id)
    return {"ok": ok, "watchers": list_watchers(item_id)}


@router_work_queue.get("/ui/work-items/{item_id}/watchers", tags=["WidgetMVP"])
def ui_watchers_list(item_id: str) -> dict[str, Any]:
    if not get_work_item(item_id): raise HTTPException(status_code=404, detail="not_found")
    return {"watchers": list_watchers(item_id)}


@router_work_queue.delete("/ui/work-items/{item_id}/watchers", tags=["WidgetMVP"])
def ui_watchers_remove(item_id: str, user_id: str = Query(...)) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    ok = remove_watcher(item_id, user_id)
    return {"ok": ok, "watchers": list_watchers(item_id)}


# ═══════════════════════════════════════════════════════════════
# Bloco G — Métricas: cycle time, lead time
# ═══════════════════════════════════════════════════════════════

@router_work_queue.get("/ui/work-items/metrics/cycle-time", tags=["WidgetMVP"])
def ui_metrics_cycle_time(tenant_id: str = Query(default="default")) -> dict[str, Any]:
    if not memory_db_enabled(): return {"items": [], "work_items_enabled": False}
    items = list_work_items(limit=500)
    done_items = [i for i in items if i.get("status") == "done" and i.get("closed_at")]
    times = []
    for i in done_items:
        created = i.get("created_at", "")
        closed = i.get("closed_at", "")
        if created and closed:
            try:
                from datetime import datetime
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                d = datetime.fromisoformat(closed.replace("Z", "+00:00"))
                hours = (d - c).total_seconds() / 3600
                times.append({"id": i["id"], "title": i["title"], "cycle_hours": round(hours, 1)})
            except Exception: pass
    avg = round(sum(t["cycle_hours"] for t in times) / len(times), 1) if times else 0
    return {"items": times[-20:], "average_cycle_hours": avg, "total_completed": len(times)}


@router_work_queue.get("/ui/work-items/metrics/lead-time", tags=["WidgetMVP"])
def ui_metrics_lead_time(assignee_id: str = Query(...)) -> dict[str, Any]:
    if not memory_db_enabled(): return {"items": [], "work_items_enabled": False}
    items = list_work_items(assignee_id=assignee_id, limit=200)
    done = [i for i in items if i.get("status") == "done" and i.get("closed_at")]
    times = []
    for i in done:
        created = i.get("created_at", "")
        closed = i.get("closed_at", "")
        if created and closed:
            try:
                from datetime import datetime
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                d = datetime.fromisoformat(closed.replace("Z", "+00:00"))
                hours = (d - c).total_seconds() / 3600
                times.append(round(hours, 1))
            except Exception: pass
    avg = round(sum(times) / len(times), 1) if times else 0
    return {"assignee_id": assignee_id, "completed": len(times), "average_lead_hours": avg, "lead_times": times[-20:]}


# ═══════════════════════════════════════════════════════════════
# Bloco F3 — Webhooks on status change
# ═══════════════════════════════════════════════════════════════

_webhooks: dict[str, list[str]] = {}  # tenant_id → [url, ...]

def add_webhook(url: str, *, tenant_id: str = "default") -> bool:
    tid = tenant_id or "default"
    _webhooks.setdefault(tid, [])
    if url not in _webhooks[tid]:
        _webhooks[tid].append(url)
    return True

def remove_webhook(url: str, *, tenant_id: str = "default") -> bool:
    tid = tenant_id or "default"
    if tid in _webhooks and url in _webhooks[tid]:
        _webhooks[tid].remove(url)
    return True

def _fire_webhooks(item: dict, event: str, tenant_id: str) -> None:
    """Fire webhooks asynchronously (best-effort)."""
    urls = _webhooks.get(tenant_id, [])
    if not urls:
        return
    import json as _json, urllib.request as _req, threading as _th
    payload = _json.dumps({"event": event, "work_item": item, "tenant_id": tenant_id}, default=str)
    def _post(url):
        try:
            r = _req.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"}, method="POST")
            _req.urlopen(r, timeout=5)
        except Exception:
            pass
    for url in urls:
        _th.Thread(target=_post, args=(url,), daemon=True).start()


@router_work_queue.post("/ui/work-items/webhooks", tags=["WidgetMVP"])
def ui_webhooks_add(url: str = Query(...)) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role("admin", "lead")
    add_webhook(url)
    return {"ok": True, "url": url}

@router_work_queue.get("/ui/work-items/webhooks", tags=["WidgetMVP"])
def ui_webhooks_list() -> dict[str, Any]:
    return {"urls": _webhooks.get("default", [])}

@router_work_queue.delete("/ui/work-items/webhooks", tags=["WidgetMVP"])
def ui_webhooks_remove(url: str = Query(...)) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role("admin", "lead")
    remove_webhook(url)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# Bloco G4 — sort_order + G5 reorder + G6 batch
# ═══════════════════════════════════════════════════════════════

class ReorderBody(BaseModel):
    items: list[dict]  # [{"id": "WI-1", "sort_order": 0}, ...]

class BatchBody(BaseModel):
    item_ids: list[str]
    status: str

@router_work_queue.patch("/ui/work-items/reorder", tags=["WidgetMVP"])
def ui_work_items_reorder(body: ReorderBody) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    updated = 0
    for item in body.items:
        iid = str(item.get("id", "")).strip()
        order = int(item.get("sort_order", 0))
        if iid:
            try:
                ensure_work_items_schema()
                with connect_pg() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE work_items SET sort_order=%s WHERE id=%s", (order, iid))
                updated += 1
            except Exception:
                pass
    return {"ok": True, "updated": updated}

@router_work_queue.patch("/ui/work-items/batch", tags=["WidgetMVP"])
def ui_work_items_batch(body: BatchBody) -> dict[str, Any]:
    from app.shared.rbac import require_any_role
    require_any_role(*WORK_ITEM_MUTATION_ROLES)
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    if body.status not in VALID_STATUS:
        raise HTTPException(status_code=422, detail="invalid_status")
    updated = 0
    for iid in body.item_ids:
        item = patch_work_item(iid.strip(), status=body.status)
        if item:
            _fire_webhooks(item, f"status_{body.status}", "default")
            updated += 1
    return {"ok": True, "updated": updated, "status": body.status}


# ═══════════════════════════════════════════════════════════════
# Bloco G3 — Cumulative flow
# ═══════════════════════════════════════════════════════════════

@router_work_queue.get("/ui/work-items/metrics/cumulative-flow", tags=["WidgetMVP"])
def ui_metrics_cumulative_flow(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    if not memory_db_enabled():
        return {"items": [], "work_items_enabled": False}
    items = list_work_items(limit=1000)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    flow: list[dict] = []
    for d in range(days, -1, -1):
        date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        counts = {s: 0 for s in VALID_STATUS}
        for i in items:
            created = i.get("created_at", "")[:10]
            closed = (i.get("closed_at") or "9999")[:10]
            if created <= date and (i.get("status") != "done" or closed >= date):
                st = i.get("status", "open")
                if st == "done" and closed < date:
                    continue
                counts[st] = counts.get(st, 0) + 1
        flow.append({"date": date, **counts})
    return {"items": flow, "days": days}
