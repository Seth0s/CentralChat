"""Connector domain — registry, status, jobs, file tools, shell execution."""

from __future__ import annotations

from __future__ import annotations
from app.clients import call_llm
from app.config import CENTRAL_CLIENT_JOBS_ENABLED, CENTRAL_CLIENT_JOB_LEASE_SECONDS, CENTRAL_CLIENT_JOB_MAX_RETRIES, MEMORY_DB_URL, MEMORY_ENABLED
from app.config import CENTRAL_CONNECTOR_HEARTBEAT_TTL_SECONDS
from app.config import REQUEST_SHELL_SUMMARY_ENABLED, REQUEST_SHELL_SUMMARY_MIN_CHARS
from app.config import SHELL_GATEWAY_CONNECT_TIMEOUT, SHELL_GATEWAY_HTTP_TIMEOUT, SHELL_GATEWAY_TOKEN, SHELL_GATEWAY_URL
from app.config import SHELL_REQUEST_CWD_PREFIX_ALLOWLIST_RAW
from app.config import SHELL_UNKNOWN_LOG_PATH
from app.shared.approvals_store import resolve_tenant_id_for_store
from app.shared.modality_models import resolve_modality_call_params
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.pg_tenant import connect_pg, resolve_pg_tenant_id
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.tenant_paths import sanitize_client_id
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any
from typing import Any, Literal
import httpx
import json
import os
import re
import uuid


# ═══ CONNECTOR_REGISTRY ═══

"""ADR-017 — connector registration and heartbeat (Postgres)."""

_CONNECTOR_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")

# Prevent request-time DDL races + noisy logs when multiple connector requests arrive.
_CLIENT_JOBS_SCHEMA_READY = False
_CLIENT_JOBS_SCHEMA_LOCK = threading.Lock()
def sanitize_connector_id(raw: str) -> str:
    s = (raw or "").strip()
    if not _CONNECTOR_ID_RE.fullmatch(s):
        raise ValueError("invalid_connector_id")
    return s

def _resolve_tenant(*, tenant_id: str | None = None) -> str:
    if tenant_id and str(tenant_id).strip():
        return sanitize_client_id(str(tenant_id).strip())
    return resolve_pg_tenant_id()

def register_connector(
    *,
    tenant_id: str | None,
    connector_id: str,
    capabilities: list[str],
    protocol_version: str = "1",
    device_label: str | None = None,
) -> dict[str, Any]:
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    tid = _resolve_tenant(tenant_id=tenant_id)
    cid = sanitize_connector_id(connector_id)
    caps = [str(c).strip() for c in capabilities if str(c).strip()]
    pv = (protocol_version or "1").strip() or "1"
    label = (device_label or "").strip() or None
    ensure_client_jobs_schema()
    now = datetime.now(timezone.utc)
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO connectors (
                  connector_id, tenant_id, capabilities, protocol_version,
                  device_label, last_seen_at, registered_at
                )
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, connector_id) DO UPDATE SET
                  capabilities = EXCLUDED.capabilities,
                  protocol_version = EXCLUDED.protocol_version,
                  device_label = COALESCE(EXCLUDED.device_label, connectors.device_label),
                  last_seen_at = EXCLUDED.last_seen_at;
                """,
                (cid, tid, json.dumps(caps), pv, label, now, now),
            )
    return {
        "connector_id": cid,
        "tenant_id": tid,
        "capabilities": caps,
        "protocol_version": pv,
        "device_label": label,
        "last_seen_at": now.isoformat(),
        "status": "registered",
    }

def heartbeat_connector(
    *,
    tenant_id: str | None,
    connector_id: str,
) -> dict[str, Any] | None:
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    tid = _resolve_tenant(tenant_id=tenant_id)
    cid = sanitize_connector_id(connector_id)
    ensure_client_jobs_schema()
    now = datetime.now(timezone.utc)
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE connectors
                SET last_seen_at = %s
                WHERE tenant_id = %s AND connector_id = %s
                RETURNING connector_id, device_label, protocol_version;
                """,
                (now, tid, cid),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "connector_id": cid,
        "tenant_id": tid,
        "last_seen_at": now.isoformat(),
        "status": "ok",
    }

def list_online_connectors(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    if not client_jobs_db_enabled():
        return []
    tid = _resolve_tenant(tenant_id=tenant_id)
    ensure_client_jobs_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connector_id, capabilities, protocol_version, device_label, last_seen_at
                FROM connectors
                WHERE tenant_id = %s
                  AND last_seen_at >= (now() - (%s || ' seconds')::interval)
                ORDER BY last_seen_at DESC;
                """,
                (tid, str(CENTRAL_CONNECTOR_HEARTBEAT_TTL_SECONDS)),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "connector_id": str(row[0]),
                "tenant_id": tid,
                "capabilities": row[1] if isinstance(row[1], list) else [],
                "protocol_version": str(row[2] or "1"),
                "device_label": str(row[3]) if row[3] else None,
                "last_seen_at": row[4].isoformat() if row[4] else None,
                "online": True,
            }
        )
    return out


# ═══ CONNECTOR_STATUS ═══

"""Public connector status snapshot for GET /config (ADR-017 phase 6)."""

def build_connector_status_public_snapshot(*, tenant_id: str | None = None) -> dict[str, Any]:
    """
    Tenant-scoped connector presence for the widget UI.

    When legacy VPS shell is active or Postgres jobs are disabled, reports
    ``client_execution_enabled: false`` so the UI does not prompt for a local agent.
    """
    if not tenant_shell_uses_client_connector() or not client_jobs_db_enabled():
        return {
            "client_execution_enabled": False,
            "online": False,
            "connector_count": 0,
            "connectors": [],
        }
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    online = list_online_connectors(tenant_id=tid)
    connectors: list[dict[str, Any]] = []
    for row in online[:8]:
        connectors.append(
            {
                "connector_id": row.get("connector_id"),
                "device_label": row.get("device_label"),
                "capabilities": row.get("capabilities") or [],
                "last_seen_at": row.get("last_seen_at"),
            }
        )
    return {
        "client_execution_enabled": True,
        "online": len(online) > 0,
        "connector_count": len(online),
        "connectors": connectors,
    }


# ═══ CLIENT_FILE_TOOLS ═══

"""ADR-017 phase 7 — client_read_file / client_grep via client_jobs (connector)."""

FILE_READ_ACTION_ID = "file.read"

FILE_GREP_ACTION_ID = "file.grep"

_TOOL_CALL_PREFIX = {
    "client_read_file": "read",
    "client_grep": "grep",
}

def _session_id_from_ctx(ctx: dict[str, Any] | None) -> str | None:
    if not ctx:
        return None
    sid = str(ctx.get("chat_session_id") or "").strip()
    return sid if len(sid) >= 8 else None

def validate_client_path(path: str) -> str | None:
    """Return error code or None if path is acceptable for connector payload."""
    p = (path or "").strip()
    if not p:
        return "path_required"
    if "\0" in p:
        return "invalid_path"
    if len(p) > 4096:
        return "path_too_long"
    if p.startswith("-"):
        return "invalid_path"
    return None

def build_read_payload(arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    path = str(arguments.get("path") or "").strip()
    err = validate_client_path(path)
    if err:
        return None, err
    mb = arguments.get("max_bytes", 32768)
    if not isinstance(mb, int):
        mb = 32768
    mb = max(256, min(512_000, int(mb)))
    return {"path": path, "max_bytes": mb}, None

def build_grep_payload(arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    path = str(arguments.get("path") or "").strip()
    pattern = str(arguments.get("pattern") or "").strip()
    if not pattern:
        return None, "pattern_required"
    err = validate_client_path(path)
    if err:
        return None, err
    if len(pattern) > 400:
        return None, "pattern_too_long"
    mm = arguments.get("max_matches", 80)
    if not isinstance(mm, int):
        mm = 80
    mm = max(1, min(500, int(mm)))
    return {"path": path, "pattern": pattern, "max_matches": mm}, None

def enqueue_client_file_job(
    *,
    tenant_id: str,
    action_id: str,
    payload: dict[str, Any],
    request_id: str,
    tool_name: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    tid = resolve_tenant_id_for_store(tenant_id)
    prefix = _TOOL_CALL_PREFIX.get(tool_name, "client")
    tcid = f"{prefix}-{request_id}"
    sid = (session_id or "").strip()
    return create_job(
        tenant_id=tid,
        action_id=action_id,
        payload=dict(payload),
        tool_call_id=tcid,
        session_id=sid if len(sid) >= 8 else None,
    )

def _dispatch_client_file_tool(
    *,
    tool_name: str,
    action_id: str,
    arguments: dict[str, Any],
    request_id: str,
    canvas_write_ctx: dict[str, Any] | None,
    build_payload,
) -> dict[str, Any]:
    if not tenant_shell_uses_client_connector():
        return {
            "ok": False,
            "error": "client_execution_disabled",
            "request_id": request_id,
            "message_pt": (
                "Leitura e pesquisa local estao desactivadas neste ambiente "
                "(modo legado da plataforma)."
            ),
        }
    tid = resolve_tenant_id_for_store()
    if not connector_online_for_tenant(tenant_id=tid):
        return build_client_agent_offline_response(request_id=request_id)
    body, verr = build_payload(arguments)
    if verr or body is None:
        return {
            "ok": False,
            "error": verr or "invalid_arguments",
            "request_id": request_id,
        }
    job = enqueue_client_file_job(
        tenant_id=tid,
        action_id=action_id,
        payload=body,
        request_id=request_id,
        tool_name=tool_name,
        session_id=_session_id_from_ctx(canvas_write_ctx),
    )
    return build_job_queued_shell_response(
        job=job,
        request_id=request_id,
        classification=tool_name,
    )

def dispatch_client_read_file(
    *,
    arguments: dict[str, Any],
    request_id: str,
    canvas_write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_client_file_tool(
        tool_name="client_read_file",
        action_id=FILE_READ_ACTION_ID,
        arguments=arguments,
        request_id=request_id,
        canvas_write_ctx=canvas_write_ctx,
        build_payload=build_read_payload,
    )

def dispatch_client_grep(
    *,
    arguments: dict[str, Any],
    request_id: str,
    canvas_write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_client_file_tool(
        tool_name="client_grep",
        action_id=FILE_GREP_ACTION_ID,
        arguments=arguments,
        request_id=request_id,
        canvas_write_ctx=canvas_write_ctx,
        build_payload=build_grep_payload,
    )


# ═══ CLIENT_JOBS_STORE ═══

"""ADR-017 — persisted client_jobs queue (Postgres + RLS)."""

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore

JobStatus = Literal[
    "queued",
    "dispatched",
    "running",
    "succeeded",
    "failed",
    "expired",
    "denied",
]

_RESULT_JSON_MAX_CHARS = 64_000

def client_jobs_db_enabled() -> bool:
    from app import config as cfg  # noqa: PLC0415

    return bool(
        cfg.CENTRAL_CLIENT_JOBS_ENABLED
        and memory_db_enabled()
        and (cfg.MEMORY_DB_URL or "").strip()
    )

def _resolve_tenant(*, tenant_id: str | None = None) -> str:
    if tenant_id and str(tenant_id).strip():
        return sanitize_client_id(str(tenant_id).strip())
    return resolve_pg_tenant_id()

def _connect_jobs_admin() -> Any:
    """DB owner connection for cross-tenant dispatcher (bypasses RLS for table owner)."""
    from app import config as cfg  # noqa: PLC0415

    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    url = (cfg.MEMORY_DB_URL or "").strip()
    if not url:
        raise RuntimeError("memory_db_url_missing")
    return psycopg.connect(url, autocommit=True)

def ensure_client_jobs_schema() -> None:
    if not client_jobs_db_enabled():
        return
    global _CLIENT_JOBS_SCHEMA_READY
    if _CLIENT_JOBS_SCHEMA_READY:
        return
    with _CLIENT_JOBS_SCHEMA_LOCK:
        if _CLIENT_JOBS_SCHEMA_READY:
            return
    sql_path = (
        Path(__file__).resolve().parents[2] / "deploy" / "postgres" / "init" / "04-client-jobs.sql"
    )
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn:
        with conn.cursor() as cur:
            if sql_path.is_file():
                cur.execute(sql_path.read_text(encoding="utf-8"))
            else:
                _ensure_client_jobs_schema_inline(cur)
            _CLIENT_JOBS_SCHEMA_READY = True

def _ensure_client_jobs_schema_inline(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS connectors (
          connector_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
          protocol_version TEXT NOT NULL DEFAULT '1',
          device_label TEXT,
          last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, connector_id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_jobs (
          job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id TEXT NOT NULL,
          connector_id TEXT,
          action_id TEXT NOT NULL,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          status TEXT NOT NULL DEFAULT 'queued',
          lease_until TIMESTAMPTZ,
          approval_id TEXT,
          session_id TEXT,
          tool_call_id TEXT,
          result JSONB,
          error_code TEXT,
          retry_count INT NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS client_jobs_tenant_status_created
        ON client_jobs (tenant_id, status, created_at ASC);
        """
    )
    cur.execute("ALTER TABLE connectors ENABLE ROW LEVEL SECURITY;")
    cur.execute("DROP POLICY IF EXISTS connectors_tenant_rls ON connectors;")
    cur.execute(
        """
        DO $$
        BEGIN
          CREATE POLICY connectors_tenant_rls ON connectors
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    cur.execute("ALTER TABLE client_jobs ENABLE ROW LEVEL SECURITY;")
    cur.execute("DROP POLICY IF EXISTS client_jobs_tenant_rls ON client_jobs;")
    cur.execute(
        """
        DO $$
        BEGIN
          CREATE POLICY client_jobs_tenant_rls ON client_jobs
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

def _row_to_job(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "job_id": str(row[0]),
        "tenant_id": str(row[1]),
        "connector_id": str(row[2]) if row[2] else None,
        "action_id": str(row[3]),
        "payload": row[4] if isinstance(row[4], dict) else {},
        "status": str(row[5]),
        "lease_until": row[6].isoformat() if row[6] else None,
        "approval_id": str(row[7]) if row[7] else None,
        "session_id": str(row[8]) if row[8] else None,
        "tool_call_id": str(row[9]) if row[9] else None,
        "result": row[10] if isinstance(row[10], dict) else None,
        "error_code": str(row[11]) if row[11] else None,
        "retry_count": int(row[12] or 0),
        "created_at": row[13].isoformat() if row[13] else None,
        "updated_at": row[14].isoformat() if row[14] else None,
    }

def _truncate_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    raw = json.dumps(result, ensure_ascii=False)
    if len(raw) <= _RESULT_JSON_MAX_CHARS:
        return result
    return {"truncated": True, "preview": raw[:_RESULT_JSON_MAX_CHARS]}

def create_job(
    *,
    tenant_id: str,
    action_id: str,
    payload: dict[str, Any],
    status: JobStatus = "queued",
    approval_id: str | None = None,
    session_id: str | None = None,
    tool_call_id: str | None = None,
    connector_id: str | None = None,
) -> dict[str, Any]:
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    tid = _resolve_tenant(tenant_id=tenant_id)
    aid = (action_id or "").strip()
    if not aid:
        raise ValueError("action_id_required")
    job_id = str(uuid.uuid4())
    ensure_client_jobs_schema()
    now = datetime.now(timezone.utc)
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO client_jobs (
                  job_id, tenant_id, connector_id, action_id, payload, status,
                  approval_id, session_id, tool_call_id, created_at, updated_at
                )
                VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING job_id, tenant_id, connector_id, action_id, payload, status,
                          lease_until, approval_id, session_id, tool_call_id,
                          result, error_code, retry_count, created_at, updated_at;
                """,
                (
                    job_id,
                    tid,
                    connector_id,
                    aid,
                    json.dumps(payload),
                    status,
                    approval_id,
                    session_id,
                    tool_call_id,
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
    assert row is not None
    return _row_to_job(row)

_SELECT_JOB_ROW = """
    SELECT job_id, tenant_id, connector_id, action_id, payload, status,
           lease_until, approval_id, session_id, tool_call_id,
           result, error_code, retry_count, created_at, updated_at
"""

def fetch_queued_jobs(
    *,
    tenant_id: str | None,
    connector_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Legacy poll of ``queued`` jobs (prefer ``fetch_and_claim_jobs_for_connector``)."""
    if not client_jobs_db_enabled():
        return []
    tid = _resolve_tenant(tenant_id=tenant_id)
    lim = max(1, min(100, int(limit)))
    ensure_client_jobs_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            if connector_id:
                cur.execute(
                    f"""
                    {_SELECT_JOB_ROW}
                    FROM client_jobs
                    WHERE tenant_id = %s AND status = 'queued'
                      AND (connector_id IS NULL OR connector_id = %s)
                    ORDER BY created_at ASC
                    LIMIT %s;
                    """,
                    (tid, connector_id.strip(), lim),
                )
            else:
                cur.execute(
                    f"""
                    {_SELECT_JOB_ROW}
                    FROM client_jobs
                    WHERE tenant_id = %s AND status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT %s;
                    """,
                    (tid, lim),
                )
            rows = cur.fetchall()
    return [_row_to_job(r) for r in rows]

def pick_fair_queued_jobs(*, limit: int) -> list[dict[str, Any]]:
    """
    One oldest ``queued`` job per tenant (round-robin fairness across tenants).
    Uses admin connection (dispatcher).
    """
    if not client_jobs_db_enabled():
        return []
    lim = max(1, min(200, int(limit)))
    ensure_client_jobs_schema()
    with _connect_jobs_admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (tenant_id)
                       job_id, tenant_id, connector_id, action_id, payload, status,
                       lease_until, approval_id, session_id, tool_call_id,
                       result, error_code, retry_count, created_at, updated_at
                FROM client_jobs
                WHERE status = 'queued'
                ORDER BY tenant_id, created_at ASC
                LIMIT %s;
                """,
                (lim,),
            )
            rows = cur.fetchall()
    return [_row_to_job(r) for r in rows]

def dispatch_job_to_connector(
    *,
    tenant_id: str,
    job_id: str,
    connector_id: str,
    lease_until: datetime,
) -> dict[str, Any] | None:
    """``queued`` → ``dispatched`` with lease (admin/dispatcher)."""
    if not client_jobs_db_enabled():
        return None
    tid = _resolve_tenant(tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    ensure_client_jobs_schema()
    with _connect_jobs_admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE client_jobs
                SET status = 'dispatched',
                    connector_id = %s,
                    lease_until = %s,
                    updated_at = %s
                WHERE tenant_id = %s AND job_id = %s::uuid AND status = 'queued'
                RETURNING job_id, tenant_id, connector_id, action_id, payload, status,
                          lease_until, approval_id, session_id, tool_call_id,
                          result, error_code, retry_count, created_at, updated_at;
                """,
                (connector_id, lease_until, now, tid, job_id),
            )
            row = cur.fetchone()
    return _row_to_job(row) if row else None

def process_expired_job_leases(
    *,
    now: datetime | None = None,
    lease_seconds: int | None = None,
    max_retries: int | None = None,
) -> dict[str, int]:
    """
    Requeue or fail jobs whose lease expired (``dispatched`` / ``running``).

    Returns counts: ``requeued``, ``failed``.
    """
    if not client_jobs_db_enabled():
        return {"requeued": 0, "failed": 0}
    ts = now or datetime.now(timezone.utc)
    max_r = CENTRAL_CLIENT_JOB_MAX_RETRIES if max_retries is None else max_retries
    lease_s = CENTRAL_CLIENT_JOB_LEASE_SECONDS if lease_seconds is None else lease_seconds
    _ = lease_s
    ensure_client_jobs_schema()
    requeued = 0
    failed = 0
    with _connect_jobs_admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, tenant_id, retry_count
                FROM client_jobs
                WHERE status IN ('dispatched', 'running')
                  AND lease_until IS NOT NULL
                  AND lease_until < %s
                FOR UPDATE SKIP LOCKED;
                """,
                (ts,),
            )
            rows = cur.fetchall()
            for job_id, tenant_id, retry_count in rows:
                rc = int(retry_count or 0)
                if rc < max_r:
                    cur.execute(
                        """
                        UPDATE client_jobs
                        SET status = 'queued',
                            connector_id = NULL,
                            lease_until = NULL,
                            retry_count = %s,
                            error_code = 'lease_expired_requeued',
                            updated_at = %s
                        WHERE job_id = %s::uuid AND tenant_id = %s;
                        """,
                        (rc + 1, ts, job_id, tenant_id),
                    )
                    requeued += 1
                else:
                    cur.execute(
                        """
                        UPDATE client_jobs
                        SET status = 'failed',
                            error_code = 'lease_expired',
                            updated_at = %s
                        WHERE job_id = %s::uuid AND tenant_id = %s;
                        """,
                        (ts, job_id, tenant_id),
                    )
                    failed += 1
    return {"requeued": requeued, "failed": failed}

def fetch_and_claim_jobs_for_connector(
    *,
    tenant_id: str | None,
    connector_id: str,
    limit: int = 20,
    lease_seconds: int | None = None,
) -> list[dict[str, Any]]:
    """
    Poll path (MVP): return ``dispatched`` jobs for this connector and mark ``running``.

    Transport: long-poll HTTP only (no WebSocket push in this phase).
    """
    if not client_jobs_db_enabled():
        return []
    tid = _resolve_tenant(tenant_id=tenant_id)
    cid = connector_id.strip()
    lim = max(1, min(100, int(limit)))
    lease_s = CENTRAL_CLIENT_JOB_LEASE_SECONDS if lease_seconds is None else lease_seconds
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=lease_s)
    ensure_client_jobs_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_id FROM client_jobs
                WHERE tenant_id = %s AND connector_id = %s
                  AND status = 'dispatched'
                  AND (lease_until IS NULL OR lease_until > %s)
                ORDER BY created_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED;
                """,
                (tid, cid, now, lim),
            )
            ids = [str(r[0]) for r in cur.fetchall()]
            if not ids:
                return []
            cur.execute(
                f"""
                UPDATE client_jobs
                SET status = 'running',
                    lease_until = %s,
                    updated_at = %s
                WHERE tenant_id = %s AND connector_id = %s
                  AND job_id = ANY(%s::uuid[])
                  AND status = 'dispatched'
                RETURNING job_id, tenant_id, connector_id, action_id, payload, status,
                          lease_until, approval_id, session_id, tool_call_id,
                          result, error_code, retry_count, created_at, updated_at;
                """,
                (lease_until, now, tid, cid, ids),
            )
            rows = cur.fetchall()
    return [_row_to_job(r) for r in rows]

def find_job_by_approval_id(*, tenant_id: str, approval_id: str) -> dict[str, Any] | None:
    if not client_jobs_db_enabled():
        return None
    tid = _resolve_tenant(tenant_id=tenant_id)
    aid = (approval_id or "").strip()
    if not aid:
        return None
    ensure_client_jobs_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, tenant_id, connector_id, action_id, payload, status,
                       lease_until, approval_id, session_id, tool_call_id,
                       result, error_code, retry_count, created_at, updated_at
                FROM client_jobs
                WHERE tenant_id = %s AND approval_id = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (tid, aid),
            )
            row = cur.fetchone()
    return _row_to_job(row) if row else None

def get_job(*, tenant_id: str, job_id: str) -> dict[str, Any] | None:
    if not client_jobs_db_enabled():
        return None
    tid = _resolve_tenant(tenant_id=tenant_id)
    ensure_client_jobs_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, tenant_id, connector_id, action_id, payload, status,
                       lease_until, approval_id, session_id, tool_call_id,
                       result, error_code, retry_count, created_at, updated_at
                FROM client_jobs
                WHERE tenant_id = %s AND job_id = %s::uuid;
                """,
                (tid, job_id),
            )
            row = cur.fetchone()
    return _row_to_job(row) if row else None

def submit_job_result(
    *,
    tenant_id: str | None,
    job_id: str,
    status: Literal["succeeded", "failed"],
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    connector_id: str | None = None,
) -> dict[str, Any] | None:
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    if status not in ("succeeded", "failed"):
        raise ValueError("invalid_result_status")
    tid = _resolve_tenant(tenant_id=tenant_id)
    ensure_client_jobs_schema()
    now = datetime.now(timezone.utc)
    res = _truncate_result(result)
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE client_jobs
                SET status = %s,
                    result = %s::jsonb,
                    error_code = %s,
                    connector_id = COALESCE(%s, connector_id),
                    updated_at = %s
                WHERE tenant_id = %s AND job_id = %s::uuid
                  AND status IN ('queued', 'dispatched', 'running')
                RETURNING job_id, tenant_id, connector_id, action_id, payload, status,
                          lease_until, approval_id, session_id, tool_call_id,
                          result, error_code, retry_count, created_at, updated_at;
                """,
                (
                    status,
                    json.dumps(res) if res is not None else None,
                    (error_code or "").strip() or None,
                    connector_id,
                    now,
                    tid,
                    job_id,
                ),
            )
            row = cur.fetchone()
    job = _row_to_job(row) if row else None
    if job is not None:
        _emit_job_session_events(job)
        approval_id = str(job.get("approval_id") or "").strip()
        if approval_id:
            from app.shared.approvals_store import set_execution_status

            st = str(job.get("status") or "")
            set_execution_status(
                approval_id,
                tenant_id=tid,
                execution_status=st,
                job_id=str(job.get("job_id") or ""),
                error_code=str(job.get("error_code") or "") or None,
            )
            if str(job.get("action_id") or "") == SHELL_EXEC_ACTION_ID:
                try:
                    from app.shared.orchestrator_audit import write_event as write_orchestrator_audit

                    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
                    result = job.get("result") if isinstance(job.get("result"), dict) else {}
                    write_orchestrator_audit(
                        {
                            "event": "shell_exec_completed",
                            "approval_id": approval_id,
                            "job_id": str(job.get("job_id") or ""),
                            "command": result.get("command") or payload.get("sh_c") or payload.get("preview"),
                            "cwd": result.get("cwd") or payload.get("cwd"),
                            "exit_code": result.get("exit_code"),
                            "status": st,
                            "tenant_id": tid,
                        }
                    )
                except Exception:
                    pass
    return job

def _emit_job_session_events(job: dict[str, Any]) -> None:
    try:
        from app.context import record_client_job_session_events

        record_client_job_session_events(job=job)
    except Exception:
        pass


# ═══ CLIENT_SHELL_EXECUTION ═══

"""ADR-017 phase 3 — shell.exec on tenant connector (not VPS shell-gateway)."""

SHELL_EXEC_ACTION_ID = "shell.exec"

PENDING_HITL_MESSAGE_PT = (
    "Comando pendente de aprovação humana. Será executado no teu dispositivo "
    "após aprovação, quando o agente local estiver ligado."
)

CLIENT_AGENT_OFFLINE_MESSAGE_PT = (
    "O agente local não está ligado. Liga o connector no teu dispositivo e tenta de novo."
)

def tenant_shell_uses_client_connector() -> bool:
    """Tenant widget path: shell runs on connector, not VPS shell-gateway."""
    from app import config as cfg  # noqa: PLC0415

    return not cfg.CENTRAL_LEGACY_PLATFORM_TOOLS

def connector_online_for_tenant(*, tenant_id: str | None = None) -> bool:
    if not client_jobs_db_enabled():
        return False
    tid = resolve_tenant_id_for_store(tenant_id)
    return len(list_online_connectors(tenant_id=tid)) > 0

def enqueue_shell_exec_client_job(
    *,
    tenant_id: str,
    payload: dict[str, Any],
    request_id: str,
    approval_id: str | None = None,
    tool_call_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create a queued ``shell.exec`` job (idempotent per ``approval_id`` when set)."""
    if not client_jobs_db_enabled():
        raise RuntimeError("client_jobs_disabled")
    tid = resolve_tenant_id_for_store(tenant_id)
    if approval_id:
        existing = find_job_by_approval_id(tenant_id=tid, approval_id=approval_id)
        if existing:
            return existing
        tcid = tool_call_id or f"shell-approval-{approval_id}"
    else:
        tcid = tool_call_id or f"shell-{request_id}"
    sid = (session_id or "").strip()
    return create_job(
        tenant_id=tid,
        action_id=SHELL_EXEC_ACTION_ID,
        payload=dict(payload),
        approval_id=approval_id,
        tool_call_id=tcid,
        session_id=sid if len(sid) >= 8 else None,
    )

def maybe_enqueue_shell_job_after_approval(rec: dict[str, Any]) -> dict[str, Any] | None:
    """
    After HITL approval, enqueue ``shell.exec`` on the client when not in legacy VPS mode.

    Returns the job dict when enqueued, else ``None``.
    """
    if not tenant_shell_uses_client_connector():
        return None
    if rec.get("action_id") != SHELL_EXEC_ACTION_ID:
        return None
    if rec.get("status") != "approved":
        return None
    body = rec.get("payload")
    if not isinstance(body, dict):
        return None
    return enqueue_shell_exec_client_job(
        tenant_id=str(rec.get("tenant_id") or resolve_tenant_id_for_store()),
        payload=body,
        request_id=str(rec.get("request_id") or ""),
        approval_id=str(rec.get("approval_id") or ""),
        session_id=str(rec.get("session_id") or "") or None,
    )

def build_pending_hitl_shell_response(
    *,
    rec: dict[str, Any],
    request_id: str,
    classification: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "pending_hitl",
        "classification": classification,
        "approval": rec,
        "approval_id": rec.get("approval_id"),
        "request_id": request_id,
        "message_pt": PENDING_HITL_MESSAGE_PT,
    }

def build_client_agent_offline_response(*, request_id: str, classification: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "error": "client_agent_offline",
        "request_id": request_id,
        "message_pt": CLIENT_AGENT_OFFLINE_MESSAGE_PT,
    }
    if classification:
        out["classification"] = classification
    return out

def build_job_queued_shell_response(
    *,
    job: dict[str, Any],
    request_id: str,
    classification: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "job_queued",
        "job": job,
        "job_id": job.get("job_id"),
        "request_id": request_id,
        "classification": classification,
        "message_pt": "Comando enfileirado para execução no teu dispositivo.",
    }


# ═══ SHELL_GATEWAY_CLIENT ═══

"""Cliente HTTP para shell-gateway."""

def call_shell_gateway_run(body: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not (SHELL_GATEWAY_URL or "").strip() or not (SHELL_GATEWAY_TOKEN or "").strip():
        return {"ok": False, "error": "shell_gateway_not_configured"}
    url = f"{SHELL_GATEWAY_URL.rstrip('/')}/run"
    headers = {
        "Authorization": f"Bearer {SHELL_GATEWAY_TOKEN}",
        "X-Request-Id": request_id,
    }
    timeout = httpx.Timeout(SHELL_GATEWAY_HTTP_TIMEOUT, connect=SHELL_GATEWAY_CONNECT_TIMEOUT)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"shell_gateway_http:{exc}"}
    try:
        data = response.json()
    except Exception:
        return {"ok": False, "error": "shell_gateway_invalid_json", "status_code": response.status_code}
    if response.status_code == 401:
        return {"ok": False, "error": "shell_gateway_unauthorized"}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else str(data)
        return {"ok": False, "error": str(detail), "status_code": response.status_code}
    if isinstance(data, dict):
        data.setdefault("ok", True)
        return data
    return {"ok": False, "error": "shell_gateway_unexpected_shape"}

def call_shell_gateway_reset_session(shell_session_id: str, request_id: str) -> dict[str, Any]:
    if not (SHELL_GATEWAY_URL or "").strip() or not (SHELL_GATEWAY_TOKEN or "").strip():
        return {"ok": False, "error": "shell_gateway_not_configured"}
    url = f"{SHELL_GATEWAY_URL.rstrip('/')}/session/reset"
    headers = {
        "Authorization": f"Bearer {SHELL_GATEWAY_TOKEN}",
        "X-Request-Id": request_id,
    }
    reset_timeout = httpx.Timeout(30.0, connect=SHELL_GATEWAY_CONNECT_TIMEOUT)
    try:
        with httpx.Client(timeout=reset_timeout) as client:
            response = client.post(
                url,
                json={"shell_session_id": shell_session_id},
                headers=headers,
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"shell_gateway_http:{exc}"}
    if response.status_code >= 400:
        return {"ok": False, "error": response.text[:500], "status_code": response.status_code}
    try:
        return response.json()
    except Exception:
        return {"ok": True, "status": "reset"}


# ═══ SHELL_OUTPUT_SUMMARIZE ═══

"""Optional shell output summary via ADR-016 ``summary`` modality role."""

def maybe_summarize_shell_output(
    *,
    stdout: str,
    stderr: str,
    truncated: bool,
) -> dict[str, str | bool]:
    combined = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    n = len(combined)
    if not REQUEST_SHELL_SUMMARY_ENABLED:
        return {
            "stdout": stdout,
            "stderr": stderr,
            "summary_applied": False,
        }
    if not truncated and n < REQUEST_SHELL_SUMMARY_MIN_CHARS:
        return {
            "stdout": stdout,
            "stderr": stderr,
            "summary_applied": False,
        }
    prompt = (
        "Resume em portugues (maximo ~2000 caracteres) a saida de terminal abaixo. "
        "Nao inventes factos que nao constem no texto. Preserva numeros, exit codes e caminhos relevantes.\n\n"
        + combined[:120_000]
    )
    try:
        prof, model_id = resolve_modality_call_params("summary")
        summary = call_llm(
            prompt,
            [],
            profile=prof,
            model_override=model_id,
            allowlist_mode="modality",
        ).strip()
    except Exception as exc:  # noqa: BLE001
        summary = f"[resumo_indisponivel: {exc}]"
    return {
        "stdout": stdout[:50_000],
        "stderr": stderr[:50_000],
        "shell_output_summary_pt": summary,
        "summary_applied": True,
    }


# ═══ SHELL_REQUEST_POLICY ═══

"""
Classificação determinística para request_shell (porteiro).
P0: argv + binário allowlist + sem metacharacters + cwd permitido.
sh_c: sempre P3 (fila HITL).
Desconhecido: P3 + log JSONL.
"""

Risk = Literal["P0", "P3"]

P0_BINARIES: frozenset[str] = frozenset(
    {
        "ls",
        "pwd",
        "echo",
        "cat",
        "whoami",
        "id",
        "uname",
        "hostname",
        "date",
        "df",
        "stat",
        "head",
        "tail",
        "wc",
        "sort",
        "cut",
        "basename",
        "dirname",
        "readlink",
        "test",
        "true",
        "false",
        "printenv",
        "getconf",
    }
)

_ELEVATION_RE = re.compile(
    r"\b(sudo|su\s|runuser|pkexec|dbus-send|curl|wget|ssh|scp|nc\s|netcat|telnet)\b",
    re.IGNORECASE,
)

_METACHAR_RE = re.compile(r"[;&|`$()<>\n\r]")

def _cwd_prefixes() -> list[str]:
    raw = SHELL_REQUEST_CWD_PREFIX_ALLOWLIST_RAW
    if not raw:
        return ["/central", "/tmp"]
    return [p.strip() for p in raw.split(",") if p.strip()]

def _normalize_cwd(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    c = cwd.strip()
    if not c:
        return None
    try:
        rp = os.path.realpath(c)
    except OSError:
        return None
    for pref in _cwd_prefixes():
        try:
            pfx = os.path.realpath(pref)
        except OSError:
            pfx = pref
        if rp == pfx or rp.startswith(pfx.rstrip("/") + os.sep):
            return rp
    return None

def _argv_binary_basename(argv: list[str]) -> str | None:
    if not argv:
        return None
    head = str(argv[0]).strip()
    if not head:
        return None
    return os.path.basename(head)

class ShellClassification:
    risk: Risk
    reason: str
    normalized_cwd: str | None
    gateway_body: dict[str, Any]

def classify_shell_request(
    *,
    mode: str,
    argv: list[str] | None,
    sh_c: str | None,
    cwd: str | None,
    shell_session_id: str | None,
    intent: str,
    timeout_sec: int | None,
    request_id: str,
) -> tuple[ShellClassification | None, str | None]:
    """
    (classificacao, None) ou (None, codigo_erro) se pedido invalido.
    """
    m = mode.strip().lower()
    if m not in ("argv", "sh_c"):
        return None, "invalid_mode"
    sid = (shell_session_id or "").strip() or None
    ts = timeout_sec if isinstance(timeout_sec, int) and 1 <= timeout_sec <= 600 else None
    norm_cwd = _normalize_cwd(cwd)
    if cwd and cwd.strip() and norm_cwd is None:
        return None, "cwd_not_allowed"

    base: dict[str, Any] = {
        "mode": m,
        "argv": argv,
        "sh_c": sh_c,
        "cwd": norm_cwd,
        "shell_session_id": sid,
        "intent": (intent or "").strip()[:512],
        "timeout_sec": ts,
    }

    if m == "sh_c":
        sc = (sh_c or "").strip()
        if not sc:
            return None, "empty_sh_c"
        if _ELEVATION_RE.search(sc):
            return None, "elevation_forbidden"
        body = {**base, "sh_c": sc, "argv": None}
        return ShellClassification(risk="P3", reason="sh_c_always_hitl", normalized_cwd=norm_cwd, gateway_body=body), None

    av = argv or []
    if not av:
        return None, "empty_argv"
    joined = " ".join(str(x) for x in av)
    if _ELEVATION_RE.search(joined):
        return None, "elevation_forbidden"
    if _METACHAR_RE.search(joined):
        return None, "metachar_forbidden"
    for a in av:
        s = str(a)
        if "\x00" in s or len(s) > 4096:
            return None, "argv_too_long_or_null"

    bn = _argv_binary_basename(av)
    if not bn:
        return None, "invalid_argv0"
    if bn not in P0_BINARIES:
        log_shell_unknown_event(
            {
                "event": "shell_p0_unknown_binary",
                "request_id": request_id,
                "binary": bn,
                "argv": av[:48],
            }
        )
        body = {**base, "argv": list(av)}
        return (
            ShellClassification(
                risk="P3",
                reason="unknown_binary_queue",
                normalized_cwd=norm_cwd,
                gateway_body=body,
            ),
            None,
        )

    body = {**base, "argv": list(av), "sh_c": None}
    return ShellClassification(risk="P0", reason="argv_readonly_mapped", normalized_cwd=norm_cwd, gateway_body=body), None


# ═══ SHELL_UNKNOWN_LOG ═══

"""JSONL local para pedidos shell fora do mapa P0 (feedback loop)."""

def log_shell_unknown_event(event: dict[str, Any]) -> None:
    path = SHELL_UNKNOWN_LOG_PATH
    if not path:
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
