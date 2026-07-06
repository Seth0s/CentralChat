"""Unified memory + team rules (Fase 3).

Team rules: only ``approved=true`` rows are recalled into ContextPipeline L4.
Memory items / RAG primitives remain in ``app.rag`` — re-exported here for callers.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.shared.catalog_limits import truncate_catalog_prompt
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

TEAM_RULE_EMBED_DIM = 384


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_pattern(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:2000]


def _embed_pattern(text: str) -> list[float]:
    from app.rag import embed_local_hash

    return embed_local_hash(text, dim=TEAM_RULE_EMBED_DIM)


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


VALID_LIFECYCLE = frozenset({"draft", "review", "published"})


def _ensure_lifecycle_columns(cur: Any) -> None:
    cur.execute(
        "ALTER TABLE team_agents ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'published';"
    )
    cur.execute(
        "ALTER TABLE team_skills ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'published';"
    )


def ensure_team_catalog_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS team_agents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL DEFAULT '',
                model_id TEXT,
                icon TEXT NOT NULL DEFAULT '',
                published BOOLEAN NOT NULL DEFAULT true,
                lifecycle_status TEXT NOT NULL DEFAULT 'published',
                version INTEGER NOT NULL DEFAULT 1,
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, name)
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS team_skills (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT true,
                published BOOLEAN NOT NULL DEFAULT true,
                lifecycle_status TEXT NOT NULL DEFAULT 'published',
                version INTEGER NOT NULL DEFAULT 1,
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, name)
            );"""
        )
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS team_rules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                pattern TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                proposed_by UUID,
                approved_by UUID,
                approved BOOLEAN NOT NULL DEFAULT false,
                rejected BOOLEAN NOT NULL DEFAULT false,
                rejection_context JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding vector({TEAM_RULE_EMBED_DIM}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );"""
        )
        cur.execute("ALTER TABLE team_rules ADD COLUMN IF NOT EXISTS rejected BOOLEAN NOT NULL DEFAULT false;")
        _ensure_lifecycle_columns(cur)


def list_team_agents(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text, name, prompt, model_id, icon, published, lifecycle_status, version, updated_at "
            "FROM team_agents WHERE tenant_id=%s AND lifecycle_status='published' AND published=true ORDER BY name",
            (tid,),
        )
        return [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "prompt": str(r[2] or ""),
                "model_id": str(r[3]) if r[3] else None,
                "icon": str(r[4] or ""),
                "published": bool(r[5]),
                "lifecycle_status": str(r[6] or "published"),
                "version": int(r[7] or 1),
                "updated_at": str(r[8] or ""),
            }
            for r in cur.fetchall()
        ]


def list_team_skills(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text, name, description, prompt, enabled, published, lifecycle_status, version, updated_at "
            "FROM team_skills WHERE tenant_id=%s AND lifecycle_status='published' AND published=true AND enabled=true ORDER BY name",
            (tid,),
        )
        return [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "description": str(r[2] or ""),
                "prompt": str(r[3] or ""),
                "enabled": bool(r[4]),
                "published": bool(r[5]),
                "lifecycle_status": str(r[6] or "published"),
                "version": int(r[7] or 1),
                "updated_at": str(r[8] or ""),
            }
            for r in cur.fetchall()
        ]


def _user_uuid_optional(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def list_team_agents_catalog(
    *,
    tenant_id: str | None = None,
    status: str = "all",
) -> list[dict[str, Any]]:
    """Admin listing — draft / review / published / all."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    where = "tenant_id=%s"
    params: list[Any] = [tid]
    st = (status or "all").strip().lower()
    if st in VALID_LIFECYCLE:
        where += " AND lifecycle_status=%s"
        params.append(st)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id::text, name, prompt, model_id, icon, published, lifecycle_status, version, updated_at "
            f"FROM team_agents WHERE {where} ORDER BY name",
            params,
        )
        return [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "prompt": str(r[2] or ""),
                "model_id": str(r[3]) if r[3] else None,
                "icon": str(r[4] or ""),
                "published": bool(r[5]),
                "lifecycle_status": str(r[6] or "draft"),
                "version": int(r[7] or 1),
                "updated_at": str(r[8] or ""),
            }
            for r in cur.fetchall()
        ]


def list_team_skills_catalog(
    *,
    tenant_id: str | None = None,
    status: str = "all",
) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    where = "tenant_id=%s"
    params: list[Any] = [tid]
    st = (status or "all").strip().lower()
    if st in VALID_LIFECYCLE:
        where += " AND lifecycle_status=%s"
        params.append(st)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id::text, name, description, prompt, enabled, published, lifecycle_status, version, updated_at "
            f"FROM team_skills WHERE {where} ORDER BY name",
            params,
        )
        return [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "description": str(r[2] or ""),
                "prompt": str(r[3] or ""),
                "enabled": bool(r[4]),
                "published": bool(r[5]),
                "lifecycle_status": str(r[6] or "draft"),
                "version": int(r[7] or 1),
                "updated_at": str(r[8] or ""),
            }
            for r in cur.fetchall()
        ]


def _audit_catalog(action: str, *, tenant_id: str, resource: str, metadata: dict | None = None) -> None:
    try:
        from app.audit_service import append_audit_event
        from app.shared.tenant_context import get_current_sub

        append_audit_event(
            action=action,
            tenant_id=tenant_id,
            user_id=get_current_sub(),
            resource=resource,
            metadata=dict(metadata or {}),
        )
    except Exception:
        logger.debug("catalog audit failed", exc_info=True)


def patch_team_agent_draft(
    agent_id: str,
    *,
    name: str | None = None,
    prompt: str | None = None,
    model_id: str | None = None,
    icon: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    fields: list[tuple[str, Any]] = []
    if name is not None and (name or "").strip():
        fields.append(("name", (name or "").strip()[:128]))
    if prompt is not None:
        fields.append(("prompt", truncate_catalog_prompt(prompt)))
    if model_id is not None:
        fields.append(("model_id", (model_id or "").strip() or None))
    if icon is not None:
        fields.append(("icon", (icon or "")[:64]))
    if not fields:
        return None
    ensure_team_catalog_schema()
    now = _utc_iso()
    set_clause = ", ".join(f"{col}=%s" for col, _ in fields) + ", updated_at=%s"
    params = [val for _, val in fields] + [now, tid, agent_id]
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""UPDATE team_agents SET {set_clause}
                WHERE tenant_id=%s AND id=%s::uuid AND lifecycle_status='draft'
                RETURNING id::text, name, prompt, model_id, icon, published, lifecycle_status, version, updated_at""",
            params,
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "prompt": str(row[2] or ""),
        "model_id": str(row[3]) if row[3] else None,
        "icon": str(row[4] or ""),
        "published": bool(row[5]),
        "lifecycle_status": str(row[6]),
        "version": int(row[7] or 1),
        "updated_at": str(row[8] or ""),
    }


def patch_team_skill_draft(
    skill_id: str,
    *,
    name: str | None = None,
    prompt: str | None = None,
    description: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    fields: list[tuple[str, Any]] = []
    if name is not None and (name or "").strip():
        fields.append(("name", (name or "").strip()[:128]))
    if prompt is not None:
        fields.append(("prompt", truncate_catalog_prompt(prompt)))
    if description is not None:
        fields.append(("description", (description or "")[:2000]))
    if not fields:
        return None
    ensure_team_catalog_schema()
    now = _utc_iso()
    set_clause = ", ".join(f"{col}=%s" for col, _ in fields) + ", updated_at=%s"
    params = [val for _, val in fields] + [now, tid, skill_id]
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""UPDATE team_skills SET {set_clause}
                WHERE tenant_id=%s AND id=%s::uuid AND lifecycle_status='draft'
                RETURNING id::text, name, description, prompt, enabled, published, lifecycle_status, version, updated_at""",
            params,
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "description": str(row[2] or ""),
        "prompt": str(row[3] or ""),
        "enabled": bool(row[4]),
        "published": bool(row[5]),
        "lifecycle_status": str(row[6]),
        "version": int(row[7] or 1),
        "updated_at": str(row[8] or ""),
    }


def create_team_agent_draft(
    *,
    name: str,
    prompt: str,
    model_id: str | None = None,
    created_by: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    nm = (name or "").strip()
    if len(nm) < 1 or not memory_db_enabled():
        return None
    ensure_team_catalog_schema()
    now = _utc_iso()
    uid = _user_uuid_optional(created_by)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_agents
               (tenant_id, name, prompt, model_id, published, lifecycle_status, created_by, created_at, updated_at)
               VALUES (%s,%s,%s,%s,false,'draft',%s::uuid,%s,%s)
               RETURNING id::text, name, prompt, model_id, icon, published, lifecycle_status, version, updated_at""",
            (tid, nm, truncate_catalog_prompt(prompt), model_id, uid, now, now),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "prompt": str(row[2] or ""),
        "model_id": str(row[3]) if row[3] else None,
        "icon": str(row[4] or ""),
        "published": bool(row[5]),
        "lifecycle_status": str(row[6]),
        "version": int(row[7] or 1),
        "updated_at": str(row[8] or ""),
    }


def _transition_catalog_row(
    *,
    table: str,
    row_id: str,
    from_status: str,
    to_status: str,
    publish: bool = False,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    ensure_team_catalog_schema()
    now = _utc_iso()
    cols = (
        "id::text, name, prompt, model_id, icon, published, lifecycle_status, version, updated_at"
        if table == "team_agents"
        else "id::text, name, description, prompt, enabled, published, lifecycle_status, version, updated_at"
    )
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        if publish:
            cur.execute(
                f"""UPDATE {table}
                    SET lifecycle_status=%s, published=true, version=version+1, updated_at=%s
                    WHERE tenant_id=%s AND id=%s::uuid AND lifecycle_status=%s
                    RETURNING {cols}""",
                (to_status, now, tid, row_id, from_status),
            )
        else:
            cur.execute(
                f"""UPDATE {table}
                    SET lifecycle_status=%s, published=false, updated_at=%s
                    WHERE tenant_id=%s AND id=%s::uuid AND lifecycle_status=%s
                    RETURNING {cols}""",
                (to_status, now, tid, row_id, from_status),
            )
        row = cur.fetchone()
    if not row:
        return None
    if table == "team_agents":
        return {
            "id": str(row[0]),
            "name": str(row[1]),
            "prompt": str(row[2] or ""),
            "model_id": str(row[3]) if row[3] else None,
            "icon": str(row[4] or ""),
            "published": bool(row[5]),
            "lifecycle_status": str(row[6]),
            "version": int(row[7] or 1),
            "updated_at": str(row[8] or ""),
        }
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "description": str(row[2] or ""),
        "prompt": str(row[3] or ""),
        "enabled": bool(row[4]),
        "published": bool(row[5]),
        "lifecycle_status": str(row[6]),
        "version": int(row[7] or 1),
        "updated_at": str(row[8] or ""),
    }


def submit_team_agent_review(agent_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    row = _transition_catalog_row(
        table="team_agents",
        row_id=agent_id,
        from_status="draft",
        to_status="review",
        tenant_id=tenant_id,
    )
    if row:
        _audit_catalog("team_agent.submitted_review", tenant_id=tid, resource=agent_id, metadata={"name": row.get("name")})
    return row


def publish_team_agent(agent_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    row = _transition_catalog_row(
        table="team_agents",
        row_id=agent_id,
        from_status="review",
        to_status="published",
        publish=True,
        tenant_id=tenant_id,
    )
    if row:
        _audit_catalog(
            "team_agent.published",
            tenant_id=tid,
            resource=agent_id,
            metadata={"name": row.get("name"), "version": row.get("version")},
        )
    return row


def create_team_skill_draft(
    *,
    name: str,
    prompt: str,
    description: str = "",
    created_by: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    nm = (name or "").strip()
    if len(nm) < 1 or not memory_db_enabled():
        return None
    ensure_team_catalog_schema()
    now = _utc_iso()
    uid = _user_uuid_optional(created_by)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_skills
               (tenant_id, name, description, prompt, enabled, published, lifecycle_status, created_by, created_at, updated_at)
               VALUES (%s,%s,%s,%s,true,false,'draft',%s::uuid,%s,%s)
               RETURNING id::text, name, description, prompt, enabled, published, lifecycle_status, version, updated_at""",
            (tid, nm, (description or "")[:2000], truncate_catalog_prompt(prompt), uid, now, now),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "description": str(row[2] or ""),
        "prompt": str(row[3] or ""),
        "enabled": bool(row[4]),
        "published": bool(row[5]),
        "lifecycle_status": str(row[6]),
        "version": int(row[7] or 1),
        "updated_at": str(row[8] or ""),
    }


def submit_team_skill_review(skill_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    row = _transition_catalog_row(
        table="team_skills",
        row_id=skill_id,
        from_status="draft",
        to_status="review",
        tenant_id=tenant_id,
    )
    if row:
        _audit_catalog("team_skill.submitted_review", tenant_id=tid, resource=skill_id, metadata={"name": row.get("name")})
    return row


def publish_team_skill(skill_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    row = _transition_catalog_row(
        table="team_skills",
        row_id=skill_id,
        from_status="review",
        to_status="published",
        publish=True,
        tenant_id=tenant_id,
    )
    if row:
        _audit_catalog(
            "team_skill.published",
            tenant_id=tid,
            resource=skill_id,
            metadata={"name": row.get("name"), "version": row.get("version")},
        )
    return row


def list_team_rules(
    *,
    tenant_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    where = "tenant_id=%s"
    params: list[Any] = [tid]
    st = (status or "all").strip().lower()
    if st == "pending":
        where += " AND approved=false AND rejected=false"
    elif st == "approved":
        where += " AND approved=true"
    elif st == "rejected":
        where += " AND rejected=true"
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id::text, pattern, source, approved, rejected, proposed_by::text, approved_by::text, "
            f"rejection_context, created_at, updated_at FROM team_rules WHERE {where} "
            f"ORDER BY created_at DESC LIMIT 200",
            params,
        )
        out: list[dict[str, Any]] = []
        for r in cur.fetchall():
            ctx = r[7]
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except json.JSONDecodeError:
                    ctx = {}
            out.append(
                {
                    "id": str(r[0]),
                    "pattern": str(r[1]),
                    "source": str(r[2]),
                    "approved": bool(r[3]),
                    "rejected": bool(r[4]),
                    "proposed_by": str(r[5]) if r[5] else None,
                    "approved_by": str(r[6]) if r[6] else None,
                    "rejection_context": ctx if isinstance(ctx, dict) else {},
                    "created_at": str(r[8] or ""),
                    "updated_at": str(r[9] or ""),
                }
            )
        return out


def propose_rule_from_rejection(
    *,
    pattern: str,
    tenant_id: str | None = None,
    proposed_by: str | None = None,
    approval_id: str | None = None,
    reason: str | None = None,
    action_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a pending team rule from an approval rejection (source=rejection)."""
    body = _normalize_pattern(pattern or reason or "")
    if not body:
        return None
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_team_catalog_schema()
    vec = _embed_pattern(body)
    ctx = {
        "approval_id": approval_id,
        "reason": (reason or "")[:2000],
        "action_id": action_id,
        "proposed_at": _utc_iso(),
    }
    proposed_uuid: str | None = None
    if proposed_by:
        try:
            proposed_uuid = str(UUID(str(proposed_by).strip()))
        except ValueError:
            proposed_uuid = None
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_rules
               (tenant_id, pattern, source, proposed_by, approved, rejection_context, embedding)
               VALUES (%s, %s, 'rejection', %s::uuid, false, %s::jsonb, %s::vector)
               RETURNING id::text, pattern, approved, created_at""",
            (tid, body, proposed_uuid, json.dumps(ctx, ensure_ascii=False), _vector_literal(vec)),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "pattern": str(row[1]),
            "approved": bool(row[2]),
            "created_at": str(row[3] or ""),
            "source": "rejection",
        }


def create_manual_team_rule(
    *,
    pattern: str,
    tenant_id: str | None = None,
    proposed_by: str | None = None,
) -> dict[str, Any] | None:
    body = _normalize_pattern(pattern)
    if not body or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_team_catalog_schema()
    vec = _embed_pattern(body)
    proposed_uuid: str | None = None
    if proposed_by:
        try:
            proposed_uuid = str(UUID(str(proposed_by).strip()))
        except ValueError:
            proposed_uuid = None
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_rules (tenant_id, pattern, source, proposed_by, approved, embedding)
               VALUES (%s, %s, 'manual', %s::uuid, false, %s::vector)
               RETURNING id::text, pattern, approved, created_at""",
            (tid, body, proposed_uuid, _vector_literal(vec)),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "pattern": str(row[1]),
            "approved": bool(row[2]),
            "created_at": str(row[3] or ""),
            "source": "manual",
        }


def approve_team_rule(
    rule_id: str,
    *,
    tenant_id: str | None = None,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    ensure_team_catalog_schema()
    approver: str | None = None
    if approved_by:
        try:
            approver = str(UUID(str(approved_by).strip()))
        except ValueError:
            approver = None
    now = _utc_iso()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE team_rules SET approved=true, approved_by=%s::uuid, updated_at=%s
               WHERE tenant_id=%s AND id=%s::uuid AND approved=false
               RETURNING id::text, pattern, approved, approved_by::text""",
            (approver, now, tid, rule_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        _audit_catalog(
            "team_rule.approved",
            tenant_id=tid,
            resource=str(row[0]),
            metadata={"pattern": str(row[1])},
        )
        return {
            "id": str(row[0]),
            "pattern": str(row[1]),
            "approved": bool(row[2]),
            "approved_by": str(row[3]) if row[3] else None,
        }


def reject_team_rule(
    rule_id: str,
    *,
    reason: str,
    tenant_id: str | None = None,
    rejected_by: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    text = (reason or "").strip()
    if not text or not memory_db_enabled():
        return None
    ensure_team_catalog_schema()
    rejector: str | None = None
    if rejected_by:
        try:
            rejector = str(UUID(str(rejected_by).strip()))
        except ValueError:
            rejector = None
    now = _utc_iso()
    ctx = {"review_rejection_reason": text[:2000], "rejected_at": now}
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE team_rules
               SET rejected=true, rejection_context=rejection_context || %s::jsonb, updated_at=%s
               WHERE tenant_id=%s AND id=%s::uuid AND approved=false AND rejected=false
               RETURNING id::text, pattern, source""",
            (json.dumps(ctx, ensure_ascii=False), now, tid, rule_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    _audit_catalog(
        "team_rule.rejected",
        tenant_id=tid,
        resource=str(row[0]),
        metadata={"pattern": str(row[1]), "reason": text[:500], "rejected_by": rejector},
    )
    return {
        "id": str(row[0]),
        "pattern": str(row[1]),
        "source": str(row[2]),
        "rejected": True,
    }


def patch_team_rule_pending(
    rule_id: str,
    *,
    pattern: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    body = _normalize_pattern(pattern)
    if not body or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_team_catalog_schema()
    vec = _embed_pattern(body)
    now = _utc_iso()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE team_rules SET pattern=%s, embedding=%s::vector, updated_at=%s
               WHERE tenant_id=%s AND id=%s::uuid AND approved=false AND rejected=false
               RETURNING id::text, pattern, source, approved""",
            (body, _vector_literal(vec), now, tid, rule_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "pattern": str(row[1]),
        "source": str(row[2]),
        "approved": bool(row[3]),
    }


def recall_approved_rule_patterns(*, tenant_id: str, limit: int = 8) -> list[str]:
    """Approved rules only — used by ContextPipeline L4."""
    tid = (tenant_id or "default").strip() or "default"
    if not memory_db_enabled():
        return []
    ensure_team_catalog_schema()
    try:
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pattern FROM team_rules WHERE tenant_id=%s AND approved=true "
                "ORDER BY updated_at DESC NULLS LAST, created_at DESC LIMIT %s",
                (tid, max(1, min(20, int(limit)))),
            )
            return [str(r[0]).strip() for r in cur.fetchall() if r and r[0]]
    except Exception:
        logger.debug("recall_approved_rule_patterns failed", exc_info=True)
        return []


def team_rules_counts(*, tenant_id: str | None = None) -> dict[str, int]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return {"pending": 0, "approved": 0}
    try:
        ensure_team_catalog_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM team_rules WHERE tenant_id=%s AND approved=true",
                (tid,),
            )
            approved_n = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                "SELECT COUNT(*) FROM team_rules WHERE tenant_id=%s AND approved=false AND rejected=false",
                (tid,),
            )
            pending_n = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                "SELECT COUNT(*) FROM team_rules WHERE tenant_id=%s AND rejected=true",
                (tid,),
            )
            rejected_n = int((cur.fetchone() or [0])[0] or 0)
            return {"pending": pending_n, "approved": approved_n, "rejected": rejected_n}
    except Exception:
        logger.debug("team_rules_counts failed", exc_info=True)
        return {"pending": 0, "approved": 0}


def build_ui_memory_context() -> dict[str, Any]:
    from app.rag import build_ui_memory_context as _rag_build

    ctx = _rag_build()
    counts = team_rules_counts()
    ctx["team_catalog"] = {
        "agents_table": "team_agents",
        "skills_table": "team_skills",
        "rules_table": "team_rules",
        "rules_pending": counts.get("pending", 0),
        "rules_approved": counts.get("approved", 0),
        "note_pt": "Regras pending nunca entram no prompt; só approved em L4.",
    }
    return ctx


# Re-exports — unified entry for memory/RAG callers
from app.rag import (  # noqa: E402
    ensure_memory_schema,
    search_memory,
    upsert_memory_item,
)

__all__ = [
    "TEAM_RULE_EMBED_DIM",
    "VALID_LIFECYCLE",
    "approve_team_rule",
    "create_manual_team_rule",
    "create_team_agent_draft",
    "create_team_skill_draft",
    "build_ui_memory_context",
    "ensure_memory_schema",
    "ensure_team_catalog_schema",
    "list_team_agents",
    "list_team_agents_catalog",
    "list_team_rules",
    "list_team_skills",
    "list_team_skills_catalog",
    "patch_team_agent_draft",
    "patch_team_rule_pending",
    "patch_team_skill_draft",
    "publish_team_agent",
    "publish_team_skill",
    "propose_rule_from_rejection",
    "recall_approved_rule_patterns",
    "reject_team_rule",
    "search_memory",
    "submit_team_agent_review",
    "submit_team_skill_review",
    "team_rules_counts",
    "upsert_memory_item",
]
