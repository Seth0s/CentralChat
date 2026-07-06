"""D2.1 — Business metrics for Prometheus (streams, approvals, policy)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

APPROVALS_TOTAL = Counter(
    "central_approvals_total",
    "Approval state transitions",
    ["resolution"],
)
POLICY_VIOLATIONS_TOTAL = Counter(
    "central_policy_violations_total",
    "Policy denials",
    ["error_code"],
)
STREAMS_ACTIVE = Gauge(
    "central_streams_active",
    "Active assistant SSE streams",
)
STREAMS_TOTAL = Counter(
    "central_streams_total",
    "Assistant stream outcomes",
    ["status"],
)
SIEM_OUTBOX_DEAD = Gauge(
    "central_siem_outbox_dead_total",
    "SIEM outbox dead-letter rows",
)


def inc_approval(resolution: str) -> None:
    APPROVALS_TOTAL.labels(resolution=(resolution or "unknown")[:32]).inc()


def inc_policy_violation(error_code: str | None = None) -> None:
    POLICY_VIOLATIONS_TOTAL.labels(error_code=(error_code or "unknown")[:64]).inc()


def stream_started() -> None:
    STREAMS_ACTIVE.inc()


def stream_finished(*, ok: bool) -> None:
    STREAMS_TOTAL.labels(status="ok" if ok else "error").inc()


def refresh_siem_dead_gauge(count: int) -> None:
    SIEM_OUTBOX_DEAD.set(max(0, int(count)))
