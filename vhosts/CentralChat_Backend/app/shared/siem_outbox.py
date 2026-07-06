"""C3 — SIEM outbox with retry and dead-letter."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.shared.secret_resolver import resolve_siem_hec_token, resolve_siem_webhook_urls
from app.shared.pg_tenant import connect_pg, memory_db_enabled

logger = logging.getLogger(__name__)

SIEM_ENVELOPE_VERSION = "1"
MAX_ATTEMPTS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_siem_envelope(
    *,
    action: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical SIEM envelope v1 (D-SIEM-1)."""
    return {
        "version": SIEM_ENVELOPE_VERSION,
        "source": "centralchat",
        "action": action,
        "tenant_id": tenant_id,
        "timestamp": _utc_now().isoformat(),
        "metadata": metadata or {},
    }


def ensure_siem_outbox_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS siem_outbox (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT,
                envelope JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INT NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                delivered_at TIMESTAMPTZ
            );"""
        )


def enqueue_siem_event(
    *,
    action: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    if not memory_db_enabled():
        return None
    if not resolve_siem_webhook_urls():
        return None
    envelope = build_siem_envelope(action=action, tenant_id=tenant_id, metadata=metadata)
    try:
        ensure_siem_outbox_schema()
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO siem_outbox (tenant_id, envelope)
                   VALUES (%s,%s::jsonb) RETURNING id::text""",
                (tenant_id, json.dumps(envelope, ensure_ascii=False)),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    except Exception:
        logger.debug("enqueue_siem_event failed", exc_info=True)
        return None


def _post_envelope(url: str, envelope: dict[str, Any]) -> None:
    """HEC-compatible when token set; otherwise plain JSON POST."""
    headers = {"Content-Type": "application/json"}
    body: str
    hec_token = resolve_siem_hec_token()
    if hec_token and "services/collector" in url:
        headers["Authorization"] = f"Splunk {hec_token}"
        hec = {
            "time": int(_utc_now().timestamp()),
            "source": envelope.get("source", "centralchat"),
            "sourcetype": "_json",
            "event": envelope,
        }
        body = json.dumps(hec, ensure_ascii=False)
    else:
        body = json.dumps(envelope, ensure_ascii=False)
    resp = httpx.post(url, content=body, headers=headers, timeout=8.0)
    resp.raise_for_status()


def process_siem_outbox(*, batch_size: int = 50) -> dict[str, int]:
    """Drain pending outbox rows. Returns counts."""
    counts = {"delivered": 0, "retried": 0, "dead": 0}
    if not memory_db_enabled() or not resolve_siem_webhook_urls():
        return counts
    ensure_siem_outbox_schema()
    now = _utc_now().isoformat()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, envelope, attempts
               FROM siem_outbox
               WHERE status='pending' AND next_attempt_at <= %s
               ORDER BY created_at ASC LIMIT %s""",
            (now, batch_size),
        )
        rows = cur.fetchall()
    for row_id, _tid, envelope_raw, attempts in rows:
        if isinstance(envelope_raw, str):
            envelope = json.loads(envelope_raw)
        else:
            envelope = envelope_raw
        ok = False
        last_err = ""
        for url in resolve_siem_webhook_urls():
            try:
                _post_envelope(url, envelope)
                ok = True
                break
            except Exception as exc:
                last_err = str(exc)[:500]
        with connect_pg() as conn, conn.cursor() as cur:
            if ok:
                cur.execute(
                    """UPDATE siem_outbox SET status='delivered', delivered_at=now()
                       WHERE id=%s::uuid""",
                    (row_id,),
                )
                counts["delivered"] += 1
            else:
                nxt = int(attempts or 0) + 1
                if nxt >= MAX_ATTEMPTS:
                    cur.execute(
                        """UPDATE siem_outbox SET status='dead', attempts=%s, last_error=%s
                           WHERE id=%s::uuid""",
                        (nxt, last_err, row_id),
                    )
                    counts["dead"] += 1
                    try:
                        from app.shared.alerting import send_ops_alert

                        send_ops_alert(
                            action="siem.dead_letter",
                            text=f"SIEM outbox dead-letter id={row_id} action={envelope.get('action')}",
                            metadata={"outbox_id": row_id, "last_error": last_err},
                        )
                    except Exception:
                        pass
                else:
                    backoff = min(3600, 30 * (2 ** (nxt - 1)))
                    nxt_at = (_utc_now() + timedelta(seconds=backoff)).isoformat()
                    cur.execute(
                        """UPDATE siem_outbox SET attempts=%s, last_error=%s, next_attempt_at=%s
                           WHERE id=%s::uuid""",
                        (nxt, last_err, nxt_at, row_id),
                    )
                    counts["retried"] += 1
    return counts


def siem_outbox_summary(*, tenant_id: str | None = None) -> dict[str, Any]:
    """Operational snapshot for admin SIEM monitor."""
    webhook_urls = resolve_siem_webhook_urls()
    hec_token = resolve_siem_hec_token()

    tid = (tenant_id or "").strip() or None
    out: dict[str, Any] = {
        "webhooks_configured": len(webhook_urls),
        "hec_token_configured": bool(hec_token),
        "pending": 0,
        "delivered": 0,
        "dead": 0,
        "last_error": None,
        "oldest_pending_at": None,
    }
    if not memory_db_enabled():
        out["status"] = "disabled"
        return out
    try:
        ensure_siem_outbox_schema()
        clauses = ["1=1"]
        params: list[Any] = []
        if tid:
            clauses.append("tenant_id=%s")
            params.append(tid)
        where = " AND ".join(clauses)
        with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT status, COUNT(*)::int FROM siem_outbox
                    WHERE {where} GROUP BY status""",
                params,
            )
            for status, count in cur.fetchall():
                key = str(status)
                if key in out:
                    out[key] = int(count or 0)
            cur.execute(
                f"""SELECT last_error FROM siem_outbox
                    WHERE {where} AND last_error IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1""",
                params,
            )
            err_row = cur.fetchone()
            if err_row and err_row[0]:
                out["last_error"] = str(err_row[0])[:500]
            cur.execute(
                f"""SELECT created_at::text FROM siem_outbox
                    WHERE {where} AND status='pending'
                    ORDER BY created_at ASC LIMIT 1""",
                params,
            )
            old_row = cur.fetchone()
            if old_row and old_row[0]:
                out["oldest_pending_at"] = str(old_row[0])
        out["status"] = "ok" if out["dead"] == 0 else "degraded"
    except Exception:
        logger.debug("siem_outbox_summary failed", exc_info=True)
        out["status"] = "error"
    return out
