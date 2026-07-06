"""B2.6 — Policy bundles in PG (D-POL-1)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)


def _ensure_schema(conn) -> None:  # noqa: ANN001
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_bundles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                version INT NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                label TEXT,
                created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, version)
            );
            CREATE TABLE IF NOT EXISTS policy_repo_rules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                bundle_id UUID NOT NULL REFERENCES policy_bundles(id) ON DELETE CASCADE,
                pattern TEXT NOT NULL,
                read_mode TEXT,
                write_mode TEXT,
                approval TEXT,
                sort_order INT NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS policy_tool_rules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                bundle_id UUID NOT NULL REFERENCES policy_bundles(id) ON DELETE CASCADE,
                tool TEXT NOT NULL,
                denied_pattern TEXT NOT NULL,
                sort_order INT NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tenant_active_policy (
                tenant_id TEXT PRIMARY KEY,
                bundle_id UUID NOT NULL REFERENCES policy_bundles(id),
                activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                activated_by TEXT
            );
            """
        )


def policies_from_bundle_row(
    *,
    bundle_id: str,
    version: int,
    repo_rules: list[dict[str, Any]],
    tool_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    repos: list[dict[str, Any]] = []
    for r in repo_rules:
        entry: dict[str, Any] = {"pattern": r.get("pattern")}
        if r.get("read_mode"):
            entry["read"] = r["read_mode"]
        if r.get("write_mode"):
            entry["write"] = r["write_mode"]
        if r.get("approval"):
            entry["approval"] = r["approval"]
        repos.append(entry)
    tools: dict[str, dict[str, list[str]]] = {}
    for tr in tool_rules:
        tool = str(tr.get("tool") or "")
        pat = str(tr.get("denied_pattern") or "")
        if not tool or not pat:
            continue
        tools.setdefault(tool, {"denied_patterns": []})
        tools[tool]["denied_patterns"].append(pat)
    return {
        "bundle_id": bundle_id,
        "bundle_version": version,
        "repos": repos,
        "tools": tools,
    }


def load_active_policies_from_pg(tenant_id: str) -> dict[str, Any] | None:
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    try:
        with connect_pg(tenant_id=tid) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.id, b.version
                    FROM tenant_active_policy tap
                    JOIN policy_bundles b ON b.id = tap.bundle_id
                    WHERE tap.tenant_id = %s AND b.status = 'published'
                    LIMIT 1
                    """,
                    (tid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                bundle_id, version = str(row[0]), int(row[1])
                cur.execute(
                    """
                    SELECT pattern, read_mode, write_mode, approval
                    FROM policy_repo_rules
                    WHERE bundle_id = %s::uuid
                    ORDER BY sort_order, pattern
                    """,
                    (bundle_id,),
                )
                repo_rules = [
                    {
                        "pattern": r[0],
                        "read_mode": r[1],
                        "write_mode": r[2],
                        "approval": r[3],
                    }
                    for r in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT tool, denied_pattern
                    FROM policy_tool_rules
                    WHERE bundle_id = %s::uuid
                    ORDER BY sort_order, tool
                    """,
                    (bundle_id,),
                )
                tool_rules = [{"tool": r[0], "denied_pattern": r[1]} for r in cur.fetchall()]
        return policies_from_bundle_row(
            bundle_id=bundle_id,
            version=version,
            repo_rules=repo_rules,
            tool_rules=tool_rules,
        )
    except Exception:
        logger.debug("load_active_policies_from_pg failed", exc_info=True)
        return None


def publish_policy_bundle(
    *,
    tenant_id: str,
    policies: dict[str, Any],
    label: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create new published bundle version and activate it (B2.6)."""
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    with connect_pg(tenant_id=tid) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM policy_bundles WHERE tenant_id = %s",
                (tid,),
            )
            version = int(cur.fetchone()[0])
            bundle_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO policy_bundles (id, tenant_id, version, status, label, created_by)
                VALUES (%s::uuid, %s, %s, 'published', %s, %s)
                """,
                (bundle_id, tid, version, label, created_by),
            )
            _insert_bundle_rules(cur, bundle_id=bundle_id, policies=policies)
            cur.execute(
                """
                INSERT INTO tenant_active_policy (tenant_id, bundle_id, activated_by)
                VALUES (%s, %s::uuid, %s)
                ON CONFLICT (tenant_id) DO UPDATE
                SET bundle_id = EXCLUDED.bundle_id,
                    activated_at = now(),
                    activated_by = EXCLUDED.activated_by
                """,
                (tid, bundle_id, created_by),
            )
    _audit_policy("policy.bundle_published", tenant_id=tid, bundle_id=bundle_id, metadata={"version": version, "label": label})
    return {"bundle_id": bundle_id, "version": version, "tenant_id": tid}


def _insert_bundle_rules(cur: Any, *, bundle_id: str, policies: dict[str, Any]) -> None:
    for i, rule in enumerate(policies.get("repos") or []):
        if not isinstance(rule, dict):
            continue
        cur.execute(
            """
            INSERT INTO policy_repo_rules
            (bundle_id, pattern, read_mode, write_mode, approval, sort_order)
            VALUES (%s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                bundle_id,
                str(rule.get("pattern") or ""),
                rule.get("read") or rule.get("read_mode"),
                rule.get("write") or rule.get("write_mode"),
                rule.get("approval"),
                i,
            ),
        )
    tools = policies.get("tools") if isinstance(policies.get("tools"), dict) else {}
    sort_i = 0
    for tool, cfg in tools.items():
        if not isinstance(cfg, dict):
            continue
        for pat in cfg.get("denied_patterns") or []:
            cur.execute(
                """
                INSERT INTO policy_tool_rules (bundle_id, tool, denied_pattern, sort_order)
                VALUES (%s::uuid, %s, %s, %s)
                """,
                (bundle_id, str(tool), str(pat), sort_i),
            )
            sort_i += 1


def _audit_policy(action: str, *, tenant_id: str, bundle_id: str, metadata: dict | None = None) -> None:
    try:
        from app.audit_service import append_audit_event
        from app.shared.tenant_context import get_current_sub

        append_audit_event(
            action=action,
            tenant_id=tenant_id,
            user_id=get_current_sub(),
            resource=bundle_id,
            metadata=dict(metadata or {}),
        )
    except Exception:
        logger.debug("policy audit failed", exc_info=True)


def get_policy_bundle_detail(bundle_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    try:
        with connect_pg(tenant_id=tid) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, version, status, label, created_by, created_at
                    FROM policy_bundles
                    WHERE tenant_id=%s AND id=%s::uuid
                    LIMIT 1
                    """,
                    (tid, bundle_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                bid, version, status, label, created_by, created_at = row
                cur.execute(
                    """
                    SELECT pattern, read_mode, write_mode, approval
                    FROM policy_repo_rules WHERE bundle_id=%s::uuid ORDER BY sort_order, pattern
                    """,
                    (str(bid),),
                )
                repo_rules = [
                    {"pattern": r[0], "read_mode": r[1], "write_mode": r[2], "approval": r[3]}
                    for r in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT tool, denied_pattern
                    FROM policy_tool_rules WHERE bundle_id=%s::uuid ORDER BY sort_order, tool
                    """,
                    (str(bid),),
                )
                tool_rules = [{"tool": r[0], "denied_pattern": r[1]} for r in cur.fetchall()]
        policies = policies_from_bundle_row(
            bundle_id=str(bid),
            version=int(version),
            repo_rules=repo_rules,
            tool_rules=tool_rules,
        )
        return {
            "bundle_id": str(bid),
            "version": int(version),
            "status": str(status),
            "label": label,
            "created_by": created_by,
            "created_at": str(created_at),
            "policies": policies,
        }
    except Exception:
        logger.debug("get_policy_bundle_detail failed", exc_info=True)
        return None


def get_active_policy_summary(*, tenant_id: str | None = None) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    active = load_active_policies_from_pg(tid)
    if not active:
        return {"tenant_id": tid, "active": None, "history_count": 0}
    history = list_policy_bundle_history(tid, limit=50)
    return {
        "tenant_id": tid,
        "active": active,
        "history_count": len(history),
    }


def create_policy_draft(
    *,
    tenant_id: str | None = None,
    policies: dict[str, Any],
    label: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    with connect_pg(tenant_id=tid) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM policy_bundles WHERE tenant_id = %s",
                (tid,),
            )
            version = int(cur.fetchone()[0])
            bundle_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO policy_bundles (id, tenant_id, version, status, label, created_by)
                VALUES (%s::uuid, %s, %s, 'draft', %s, %s)
                """,
                (bundle_id, tid, version, label, created_by),
            )
            _insert_bundle_rules(cur, bundle_id=bundle_id, policies=policies)
    _audit_policy("policy.draft_created", tenant_id=tid, bundle_id=bundle_id, metadata={"version": version})
    return {"bundle_id": bundle_id, "version": version, "status": "draft", "tenant_id": tid}


def update_policy_draft(
    bundle_id: str,
    *,
    policies: dict[str, Any],
    label: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    with connect_pg(tenant_id=tid) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM policy_bundles WHERE tenant_id=%s AND id=%s::uuid AND status='draft' LIMIT 1",
                (tid, bundle_id),
            )
            if not cur.fetchone():
                return None
            if label is not None:
                cur.execute(
                    "UPDATE policy_bundles SET label=%s WHERE id=%s::uuid",
                    (label, bundle_id),
                )
            cur.execute("DELETE FROM policy_repo_rules WHERE bundle_id=%s::uuid", (bundle_id,))
            cur.execute("DELETE FROM policy_tool_rules WHERE bundle_id=%s::uuid", (bundle_id,))
            _insert_bundle_rules(cur, bundle_id=bundle_id, policies=policies)
    _audit_policy("policy.draft_updated", tenant_id=tid, bundle_id=bundle_id, metadata={})
    return get_policy_bundle_detail(bundle_id, tenant_id=tid)


def publish_policy_draft(
    bundle_id: str,
    *,
    tenant_id: str | None = None,
    published_by: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    with connect_pg(tenant_id=tid) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE policy_bundles SET status='published'
                WHERE tenant_id=%s AND id=%s::uuid AND status='draft'
                RETURNING version
                """,
                (tid, bundle_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            version = int(row[0])
            cur.execute(
                """
                INSERT INTO tenant_active_policy (tenant_id, bundle_id, activated_by)
                VALUES (%s, %s::uuid, %s)
                ON CONFLICT (tenant_id) DO UPDATE
                SET bundle_id = EXCLUDED.bundle_id,
                    activated_at = now(),
                    activated_by = EXCLUDED.activated_by
                """,
                (tid, bundle_id, published_by),
            )
    _audit_policy("policy.draft_published", tenant_id=tid, bundle_id=bundle_id, metadata={"version": version})
    return {"bundle_id": bundle_id, "version": version, "status": "published", "tenant_id": tid}


def rollback_policy_bundle(
    *,
    version: int,
    tenant_id: str | None = None,
    activated_by: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return None
    with connect_pg(tenant_id=tid) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM policy_bundles
                WHERE tenant_id=%s AND version=%s AND status='published'
                LIMIT 1
                """,
                (tid, int(version)),
            )
            row = cur.fetchone()
            if not row:
                return None
            bundle_id = str(row[0])
            cur.execute(
                """
                INSERT INTO tenant_active_policy (tenant_id, bundle_id, activated_by)
                VALUES (%s, %s::uuid, %s)
                ON CONFLICT (tenant_id) DO UPDATE
                SET bundle_id = EXCLUDED.bundle_id,
                    activated_at = now(),
                    activated_by = EXCLUDED.activated_by
                """,
                (tid, bundle_id, activated_by),
            )
    _audit_policy("policy.rollback", tenant_id=tid, bundle_id=bundle_id, metadata={"version": int(version)})
    return {"bundle_id": bundle_id, "version": int(version), "tenant_id": tid, "ok": True}


def list_policy_bundle_history(tenant_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    try:
        with connect_pg(tenant_id=tid) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, version, status, label, created_by, created_at
                    FROM policy_bundles
                    WHERE tenant_id = %s
                    ORDER BY version DESC
                    LIMIT %s
                    """,
                    (tid, limit),
                )
                return [
                    {
                        "bundle_id": str(r[0]),
                        "version": int(r[1]),
                        "status": r[2],
                        "label": r[3],
                        "created_by": r[4],
                        "created_at": str(r[5]),
                    }
                    for r in cur.fetchall()
                ]
    except Exception:
        logger.debug("list_policy_bundle_history failed", exc_info=True)
        return []
