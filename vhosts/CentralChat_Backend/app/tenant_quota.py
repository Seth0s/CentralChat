"""T3 — Quota Manager: per-tenant token tracking with webhook alerts.

Checks quota before inference, increments after completion, exposes
admin endpoint GET /admin/tenant-usage/{tenant_id}.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.config import (
    CENTRAL_QUOTA_COST_PER_TOKEN_INPUT,
    CENTRAL_QUOTA_COST_PER_TOKEN_OUTPUT,
    CENTRAL_QUOTA_ENABLED,
    CENTRAL_QUOTA_PER_TENANT_PER_HOUR,
)
from app.shared.secret_resolver import resolve_quota_webhook_url
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# ═══ MODEL ═══


@dataclass
class TenantUsage:
    tenant_id: str
    period_start: str
    period_end: str
    tokens_input: int
    tokens_output: int
    cost_input: float
    cost_output: float

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def total_cost(self) -> float:
        return self.cost_input + self.cost_output

    @property
    def quota_pct(self) -> float:
        limit = CENTRAL_QUOTA_PER_TENANT_PER_HOUR
        if limit <= 0:
            return 0.0
        return min(100.0, (self.total_tokens / limit) * 100.0)


# ═══ STORE ═══


def _ensure_quota_table() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_quotas (
                id            SERIAL PRIMARY KEY,
                tenant_id     TEXT NOT NULL,
                period_start  TIMESTAMPTZ NOT NULL,
                period_end    TIMESTAMPTZ NOT NULL,
                tokens_input  BIGINT NOT NULL DEFAULT 0,
                tokens_output BIGINT NOT NULL DEFAULT 0,
                cost_input    DOUBLE PRECISION NOT NULL DEFAULT 0,
                cost_output   DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tenant_quotas_tenant_period
            ON tenant_quotas (tenant_id, period_start DESC);
            """
        )


def _current_hour_range() -> tuple[datetime, datetime]:
    """UTC hour boundary for the current period."""
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return start, end


def get_current_usage(tenant_id: str | None = None) -> TenantUsage:
    """Returns usage for the current UTC hour. Creates row if none exists."""
    if not memory_db_enabled():
        tid = tenant_id or resolve_pg_tenant_id()
        return TenantUsage(
            tenant_id=tid,
            period_start="",
            period_end="",
            tokens_input=0,
            tokens_output=0,
            cost_input=0.0,
            cost_output=0.0,
        )

    tid = tenant_id or resolve_pg_tenant_id()
    _ensure_quota_table()
    start, end = _current_hour_range()

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tokens_input, tokens_output, cost_input, cost_output
               FROM tenant_quotas
               WHERE tenant_id = %s AND period_start = %s AND period_end = %s;""",
            (tid, start, end),
        )
        row = cur.fetchone()
        if row:
            return TenantUsage(
                tenant_id=tid,
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                tokens_input=int(row[0] or 0),
                tokens_output=int(row[1] or 0),
                cost_input=float(row[2] or 0.0),
                cost_output=float(row[3] or 0.0),
            )

        cur.execute(
            """INSERT INTO tenant_quotas (tenant_id, period_start, period_end)
               VALUES (%s, %s, %s)
               ON CONFLICT DO NOTHING;""",
            (tid, start, end),
        )

    return TenantUsage(
        tenant_id=tid,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        tokens_input=0,
        tokens_output=0,
        cost_input=0.0,
        cost_output=0.0,
    )


def increment_usage(
    tenant_id: str,
    *,
    tokens_input: int = 0,
    tokens_output: int = 0,
) -> TenantUsage:
    """Atomically increment token counters by delta. Returns updated usage."""
    if not memory_db_enabled():
        return get_current_usage(tenant_id)

    tid = tenant_id.strip()
    _ensure_quota_table()
    start, end = _current_hour_range()
    cost_in = tokens_input * CENTRAL_QUOTA_COST_PER_TOKEN_INPUT
    cost_out = tokens_output * CENTRAL_QUOTA_COST_PER_TOKEN_OUTPUT

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tenant_quotas (tenant_id, period_start, period_end)
               VALUES (%s, %s, %s)
               ON CONFLICT DO NOTHING;""",
            (tid, start, end),
        )
        cur.execute(
            """UPDATE tenant_quotas
               SET tokens_input = tokens_input + %s,
                   tokens_output = tokens_output + %s,
                   cost_input = cost_input + %s,
                   cost_output = cost_output + %s,
                   updated_at = now()
               WHERE tenant_id = %s AND period_start = %s AND period_end = %s
               RETURNING tokens_input, tokens_output, cost_input, cost_output;""",
            (tokens_input, tokens_output, cost_in, cost_out, tid, start, end),
        )
        row = cur.fetchone()
        if row:
            return TenantUsage(
                tenant_id=tid,
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                tokens_input=int(row[0] or 0),
                tokens_output=int(row[1] or 0),
                cost_input=float(row[2] or 0.0),
                cost_output=float(row[3] or 0.0),
            )

    return get_current_usage(tid)


# ═══ CHECK ═══

_webhook_sent: dict[str, float] = {}
_webhook_lock = threading.Lock()
_WEBHOOK_COOLDOWN_SEC = 600  # 10 min between alerts for same tenant


def check_quota(tenant_id: str) -> tuple[bool, str | None]:
    """
    Returns (allowed, error_detail). Error_detail is None if allowed.

    When quota is at 80%+ a webhook alert fires (debounced per tenant).
    When quota is at 100%+, the request is rejected with a detail message.
    """
    if not CENTRAL_QUOTA_ENABLED:
        return True, None

    usage = get_current_usage(tenant_id)
    limit = CENTRAL_QUOTA_PER_TENANT_PER_HOUR
    if limit <= 0:
        return True, None

    pct = usage.quota_pct

    if pct >= 100.0:
        return False, (
            f"Quota horária excedida ({usage.total_tokens}/{limit} tokens, "
            f"${usage.total_cost:.4f}). Reinicia às {usage.period_end[:19]} UTC."
        )

    if pct >= 80.0:
        _maybe_send_webhook(usage, pct)
    if pct >= 90.0:
        try:
            from app.shared.alerting import send_ops_alert

            send_ops_alert(
                action="quota.threshold",
                text=f"Quota tenant `{usage.tenant_id}` at {pct:.0f}% ({usage.total_tokens}/{limit})",
                metadata={"tenant_id": usage.tenant_id, "quota_pct": pct},
            )
        except Exception:
            pass

    return True, None


def _maybe_send_webhook(usage: TenantUsage, pct: float) -> None:
    url = resolve_quota_webhook_url()
    if not url:
        return

    now = __import__("time").monotonic()
    with _webhook_lock:
        last = _webhook_sent.get(usage.tenant_id, 0.0)
        if now - last < _WEBHOOK_COOLDOWN_SEC:
            return
        _webhook_sent[usage.tenant_id] = now

    payload = {
        "text": (
            f"⚠️ Quota alert: tenant `{usage.tenant_id}` at {pct:.0f}% "
            f"({usage.total_tokens}/{CENTRAL_QUOTA_PER_TENANT_PER_HOUR} tokens, "
            f"${usage.total_cost:.4f})"
        ),
    }
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        logger.debug("quota_webhook_failed url=%s", url)


# ═══ ROUTER ═══

router_quota = APIRouter()


@router_quota.get("/admin/tenant-usage/{tenant_id}", tags=["Admin"])
def admin_tenant_usage(tenant_id: str) -> dict[str, Any]:
    """Uso actual do tenant na hora corrente."""
    usage = get_current_usage(tenant_id)
    return {
        "tenant_id": usage.tenant_id,
        "period_start": usage.period_start,
        "period_end": usage.period_end,
        "tokens_input": usage.tokens_input,
        "tokens_output": usage.tokens_output,
        "total_tokens": usage.total_tokens,
        "cost_input": round(usage.cost_input, 6),
        "cost_output": round(usage.cost_output, 6),
        "total_cost": round(usage.total_cost, 6),
        "quota_limit": CENTRAL_QUOTA_PER_TENANT_PER_HOUR,
        "quota_pct": round(usage.quota_pct, 1),
        "quota_enabled": CENTRAL_QUOTA_ENABLED,
    }


@router_quota.get("/ui/usage", tags=["WidgetMVP"])
def ui_usage() -> dict[str, Any]:
    """Per-user usage stats — tenant resolved from JWT context."""
    tid = resolve_pg_tenant_id()
    usage = get_current_usage(tid)
    return {
        "period_start": usage.period_start,
        "period_end": usage.period_end,
        "tokens_input": usage.tokens_input,
        "tokens_output": usage.tokens_output,
        "total_tokens": usage.total_tokens,
        "cost_input": round(usage.cost_input, 6),
        "cost_output": round(usage.cost_output, 6),
        "total_cost": round(usage.total_cost, 6),
        "quota_limit": CENTRAL_QUOTA_PER_TENANT_PER_HOUR,
        "quota_pct": round(usage.quota_pct, 1),
        "quota_enabled": CENTRAL_QUOTA_ENABLED,
        "period_label": "hora corrente",
    }


def get_usage_summary_24h(*, tenant_id: str | None = None, window: str = "24h") -> dict[str, Any]:
    """H2/D4 — rollup for cost dashboard (hourly buckets)."""
    from app.config import CENTRAL_QUOTA_MONTHLY_TOKENS

    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    hours_back = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}.get(window.strip().lower(), 24)
    if not memory_db_enabled():
        return {
            "tenant_id": tid,
            "window": window,
            "total_tokens": 0,
            "total_cost": 0.0,
            "monthly_limit": CENTRAL_QUOTA_MONTHLY_TOKENS,
            "monthly_pct": 0.0,
            "hours": [],
        }
    _ensure_quota_table()
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    limit_rows = min(hours_back, 720)
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT period_start, tokens_input, tokens_output, cost_input, cost_output
               FROM tenant_quotas WHERE tenant_id=%s AND period_start >= %s
               ORDER BY period_start DESC LIMIT %s""",
            (tid, since, limit_rows),
        )
        rows = cur.fetchall()
    hours: list[dict[str, Any]] = []
    total_in = total_out = 0
    total_cost = 0.0
    for r in rows:
        ti, to = int(r[1] or 0), int(r[2] or 0)
        ci, co = float(r[3] or 0), float(r[4] or 0)
        total_in += ti
        total_out += to
        total_cost += ci + co
        hours.append(
            {
                "period_start": str(r[0]),
                "tokens_input": ti,
                "tokens_output": to,
                "total_tokens": ti + to,
                "total_cost": round(ci + co, 6),
            }
        )
    total_tokens = total_in + total_out
    monthly_pct = 0.0
    if CENTRAL_QUOTA_MONTHLY_TOKENS > 0:
        monthly_pct = min(100.0, (total_tokens / CENTRAL_QUOTA_MONTHLY_TOKENS) * 100.0)
    return {
        "tenant_id": tid,
        "window": window,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "monthly_limit": CENTRAL_QUOTA_MONTHLY_TOKENS,
        "monthly_pct": round(monthly_pct, 1),
        "hours": hours,
    }
