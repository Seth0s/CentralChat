"""H1 — Append-only audit log (PG) + export CSV/JSON."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

_VALID_ROLES = frozenset({"viewer", "developer", "approver", "admin", "auditor"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_since(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.strip().lower()
    m = re.fullmatch(r"(\d+)([dhm])", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
        return _utc_now() - delta
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _payload_hash(data: Any) -> str:
    try:
        blob = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        blob = str(data)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:64]


def ensure_audit_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS audit_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                user_id UUID,
                session_id TEXT,
                approval_id UUID,
                work_item_id TEXT,
                action TEXT NOT NULL,
                resource TEXT,
                payload_hash TEXT,
                model TEXT,
                tokens_in INT,
                tokens_out INT,
                client TEXT,
                ip INET,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS audit_events_tenant_created_idx "
            "ON audit_events (tenant_id, created_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS audit_events_tenant_user_created_idx "
            "ON audit_events (tenant_id, user_id, created_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS audit_events_action_idx "
            "ON audit_events (action, created_at DESC);"
        )


def append_audit_event(
    *,
    action: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    approval_id: str | None = None,
    work_item_id: str | None = None,
    resource: str | None = None,
    model: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    client: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Insert append-only audit row. Never raises."""
    if not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    act = (action or "").strip()[:120]
    if not act:
        return None
    uid: str | None = None
    if user_id:
        try:
            uid = str(UUID(str(user_id).strip()))
        except ValueError:
            uid = None
    aid: str | None = None
    if approval_id:
        try:
            aid = str(UUID(str(approval_id).strip()))
        except ValueError:
            aid = None
    meta = dict(metadata or {})
    ph = _payload_hash(meta) if meta else None
    try:
        ensure_audit_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO audit_events
                   (tenant_id, user_id, session_id, approval_id, work_item_id, action, resource,
                    payload_hash, model, tokens_in, tokens_out, client, ip, metadata)
                   VALUES (%s,%s::uuid,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s::inet,%s::jsonb)
                   RETURNING id::text""",
                (
                    tid,
                    uid,
                    (session_id or "")[:200] or None,
                    aid,
                    (work_item_id or "")[:64] or None,
                    act,
                    (resource or "")[:500] or None,
                    ph,
                    (model or "")[:256] or None,
                    tokens_in,
                    tokens_out,
                    (client or "")[:32] or None,
                    (ip or "")[:64] or None,
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
            eid = str(row[0]) if row else None
            if eid:
                try:
                    from app.siem_dispatcher import dispatch_siem_event

                    dispatch_siem_event(action=act, tenant_id=tid, metadata=meta)
                except Exception:
                    pass
            return eid
    except Exception:
        logger.debug("append_audit_event failed action=%s", act, exc_info=True)
        return None


def mirror_orchestrator_event(event: dict[str, Any]) -> None:
    """Map JSONL orchestrator audit events into audit_events."""
    ev = str(event.get("event") or "").strip()
    if not ev:
        return
    action_map = {
        "assistant_text_stream_done": "session.turn",
        "tool_invoked": "tool.invoke",
        "tool_result_ok": "tool.result",
        "tool_result_error": "tool.error",
        "tool_denied": "tool.denied",
        "approval_resolved": "approval.resolved",
        "approval.denied": "approval.denied",
        "file_client_job_enqueued": "tool.propose_patch",
        "shell_exec_client_job_enqueued": "tool.propose_shell",
    }
    if ev == "tool_denied" and str(event.get("reason") or "").startswith("policy"):
        action = "policy.violation"
    action = action_map.get(ev, ev.replace("_", ".")[:120])
    resource = None
    if event.get("tool"):
        resource = str(event.get("tool"))
    elif event.get("approval_id"):
        resource = str(event.get("approval_id"))
    resolution = event.get("resolution")
    meta = {k: v for k, v in event.items() if k not in ("event", "ts", "source")}
    if resolution:
        meta["resolution"] = resolution
        action = f"approval.{resolution}"
    append_audit_event(
        action=action,
        session_id=str(event.get("session_id") or event.get("chat_session_id") or "") or None,
        approval_id=str(event.get("approval_id") or "") or None,
        resource=resource,
        metadata=meta,
    )


def list_audit_events(
    *,
    tenant_id: str | None = None,
    since: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    path_prefix: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if not memory_db_enabled():
        return []
    since_dt = _parse_since(since)
    clauses = ["tenant_id=%s"]
    params: list[Any] = [tid]
    if since_dt:
        clauses.append("created_at >= %s")
        params.append(since_dt.isoformat())
    if user_id:
        try:
            clauses.append("user_id=%s::uuid")
            params.append(str(UUID(user_id.strip())))
        except ValueError:
            pass
    if action:
        clauses.append("action=%s")
        params.append(action.strip())
    if path_prefix:
        clauses.append("resource LIKE %s")
        params.append(f"{path_prefix.strip()}%")
    params.append(max(1, min(1000, int(limit))))
    where = " AND ".join(clauses)
    try:
        ensure_audit_schema()
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT id::text, user_id::text, session_id, approval_id::text, work_item_id,
                    action, resource, payload_hash, model, tokens_in, tokens_out, client,
                    ip::text, metadata, created_at::text
                    FROM audit_events WHERE {where} ORDER BY created_at DESC LIMIT %s""",
                params,
            )
            out: list[dict[str, Any]] = []
            for r in cur.fetchall():
                meta = r[13]
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        meta = {}
                out.append(
                    {
                        "id": str(r[0]),
                        "user_id": str(r[1]) if r[1] else None,
                        "session_id": r[2],
                        "approval_id": str(r[3]) if r[3] else None,
                        "work_item_id": r[4],
                        "action": str(r[5]),
                        "resource": r[6],
                        "payload_hash": r[7],
                        "model": r[8],
                        "tokens_in": r[9],
                        "tokens_out": r[10],
                        "client": r[11],
                        "ip": r[12],
                        "metadata": meta if isinstance(meta, dict) else {},
                        "created_at": str(r[14] or ""),
                    }
                )
            return out
    except Exception:
        logger.debug("list_audit_events failed", exc_info=True)
        return []


def export_audit_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    fields = [
        "id", "created_at", "action", "user_id", "session_id", "approval_id",
        "work_item_id", "resource", "client", "ip", "model", "tokens_in", "tokens_out",
    ]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow({k: row.get(k) for k in fields})
    return buf.getvalue()


def export_audit_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"items": rows, "count": len(rows)}, ensure_ascii=False, indent=2)
