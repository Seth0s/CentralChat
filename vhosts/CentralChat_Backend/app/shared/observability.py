"""T8 — Observabilidade: JSON logging, aggregated metrics, cost alerts.

Provides:
- JSON log formatter with tenant_id injection
- Aggregated business metrics (10+ counters/gauges)
- GET /admin/metrics endpoint
- Cost alert webhook notifications
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter
from prometheus_client import Counter, Gauge, Histogram

from app.config import CENTRAL_QUOTA_ENABLED, CENTRAL_QUOTA_WEBHOOK_URL
from app.shared.pg_tenant import resolve_pg_tenant_id

# ═══════════════════════════════════════════════════════════════════
# T8.1 — JSON LOG FORMATTER
# ═══════════════════════════════════════════════════════════════════


class TenantJsonFormatter(logging.Formatter):
    """JSON log lines with tenant_id extracted from thread-local or request context."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            tid = resolve_pg_tenant_id()
        except Exception:
            tid = "unknown"

        log_entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "tenant_id": tid,
            "module": record.module,
            "func": record.funcName,
        }
        try:
            from app.shared.log_context import get_log_approval_id, get_log_session_id

            sid = get_log_session_id()
            aid = get_log_approval_id()
            if sid:
                log_entry["session_id"] = sid
            if aid:
                log_entry["approval_id"] = aid
        except Exception:
            pass
        if record.exc_info and record.exc_info[1]:
            log_entry["exc"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def install_json_logging() -> None:
    """Replace root handler with JSON formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(TenantJsonFormatter())
    logger = logging.getLogger()
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════
# T8.2 — AGGREGATED BUSINESS METRICS (10+ counters/gauges)
# ═══════════════════════════════════════════════════════════════════

# ── Inference ──
INFERENCE_REQUESTS_TOTAL = Counter(
    "central_inference_requests_total",
    "Total inference requests",
    ["destination", "profile"],
)
INFERENCE_TOKENS_TOTAL = Counter(
    "central_inference_tokens_total",
    "Total tokens consumed",
    ["direction", "profile"],  # direction = input|output
)
INFERENCE_ERRORS_TOTAL = Counter(
    "central_inference_errors_total",
    "Inference errors by type",
    ["error_type"],
)

# ── Quota ──
QUOTA_LIMIT_REACHED_TOTAL = Counter(
    "central_quota_limit_reached_total", "Quota limit hit count", ["tenant_class"]
)

# ── Streams ──
ACTIVE_STREAMS = Gauge(
    "central_active_streams", "Active SSE streams", ["tenant_class"]
)

# ── Tenant operations ──
TENANT_CONFIG_UPDATES_TOTAL = Counter(
    "central_tenant_config_updates_total", "Tenant config write operations"
)

# ── RAG ──
RAG_HITS_TOTAL = Counter(
    "central_rag_hits_total", "RAG hits by namespace", ["namespace"]
)
RAG_MISSES_TOTAL = Counter(
    "central_rag_misses_total", "RAG queries with 0 hits", ["namespace"]
)

# ── Embeddings ──
EMBEDDING_CACHE_GAUGE = Gauge(
    "central_embedding_cache_entries", "Embedding cache entries"
)
EMBEDDING_QUEUE_GAUGE = Gauge(
    "central_embedding_queue_pending", "Pending jobs in embedding queue"
)

# ── Latency ──
INFERENCE_LATENCY = Histogram(
    "central_inference_latency_seconds",
    "Inference request latency",
    ["profile"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

# ── Pool ──
PG_POOL_GAUGE = Gauge(
    "central_pg_pool_connections", "Active PG pool connections", ["state"]
)


def record_inference_metrics(
    profile: str,
    tokens_input: int = 0,
    tokens_output: int = 0,
    destination: str = "api",
    latency_seconds: float = 0.0,
) -> None:
    INFERENCE_REQUESTS_TOTAL.labels(destination=destination, profile=profile).inc()
    if tokens_input:
        INFERENCE_TOKENS_TOTAL.labels(direction="input", profile=profile).inc(tokens_input)
    if tokens_output:
        INFERENCE_TOKENS_TOTAL.labels(direction="output", profile=profile).inc(tokens_output)
    if latency_seconds:
        INFERENCE_LATENCY.labels(profile=profile).observe(latency_seconds)


# ═══════════════════════════════════════════════════════════════════
# T8.3 — GET /admin/metrics
# ═══════════════════════════════════════════════════════════════════

router_observability = APIRouter()


def _build_metrics_snapshot() -> dict[str, Any]:
    """Aggregate snapshot for the admin dashboard (non-Prometheus)."""
    now = time.time()

    # Embedding stats
    from app.shared.embedding_cache import embedding_cache_stats, embedding_queue_stats

    ec = embedding_cache_stats()
    eq = embedding_queue_stats()

    # Pool stats
    pool = {"available": False}
    try:
        from app.shared.pg_pool import pool_stats

        pool = pool_stats()
    except Exception:
        pass

    # Active streams (best-effort)
    active = 0
    try:
        from app.shared.concurrent_limiter import active_count

        active = active_count()
    except Exception:
        pass

    return {
        "ts_unix": now,
        "embedding": {"cache": ec, "queue": eq},
        "pg_pool": pool,
        "active_streams": active,
        "quota": {
            "enabled": CENTRAL_QUOTA_ENABLED,
            "webhook_configured": bool(CENTRAL_QUOTA_WEBHOOK_URL),
        },
    }


@router_observability.get("/admin/metrics", tags=["Admin"])
def admin_metrics() -> dict[str, Any]:
    """Aggregated observability snapshot (JSON, non-Prometheus)."""
    return _build_metrics_snapshot()


# ═══════════════════════════════════════════════════════════════════
# T8.4 — COST ALERTS
# ═══════════════════════════════════════════════════════════════════

_cost_alert_cooldown: dict[str, float] = {}
_cost_lock = threading.Lock()
_COST_COOLDOWN_SEC = 3600  # 1 hour between cost alerts


def send_cost_alert(
    *,
    tenant_id: str,
    total_cost: float,
    period: str = "hour",
) -> None:
    """Send a webhook alert when cost thresholds are reached (debounced)."""
    url = CENTRAL_QUOTA_WEBHOOK_URL
    if not url:
        return

    now = time.monotonic()
    with _cost_lock:
        last = _cost_alert_cooldown.get(tenant_id, 0.0)
        if now - last < _COST_COOLDOWN_SEC:
            return
        _cost_alert_cooldown[tenant_id] = now

    payload = {
        "text": (
            f"💰 Cost alert: tenant `{tenant_id}` "
            f"spent ${total_cost:.4f} this {period}."
        ),
    }
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        pass
