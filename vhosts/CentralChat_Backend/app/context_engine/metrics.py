"""ContextEngine Prometheus metrics emission.

Exposes metrics from the ContextEngine pipeline.
All metrics include labels: tenant_id, mode, role.

Design doc: docs/context_engine_metrics.md
"""

from __future__ import annotations

import logging
from typing import Any

from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)

# Optional prometheus import
try:
    from prometheus_client import Counter, Gauge, Histogram

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

    class _NoopMetric:
        def labels(self, **kwargs: Any) -> _NoopMetric:
            return self

        def observe(self, value: float) -> None:
            pass

        def inc(self) -> None:
            pass

        def set(self, value: float) -> None:
            pass

    Histogram = _NoopMetric  # type: ignore
    Gauge = _NoopMetric  # type: ignore
    Counter = _NoopMetric  # type: ignore


# ═══════════════════════════════════════════════════════════════
# Metric definitions
# ═══════════════════════════════════════════════════════════════

context_build_duration = Histogram(
    "context_build_duration_ms",
    "ContextEngine total build time in milliseconds",
    ["tenant_id", "mode", "role"],
    buckets=[5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000],
)

context_step_duration = Histogram(
    "context_step_duration_ms",
    "ContextEngine step duration in milliseconds",
    ["tenant_id", "step", "phase"],
    buckets=[1, 2, 5, 10, 25, 50, 100, 200, 500],
)

context_step_errors = Counter(
    "context_step_errors_total",
    "ContextEngine step errors",
    ["step"],
)

context_layers_applied = Gauge(
    "context_layers_applied",
    "Context layers applied (1 = applied)",
    ["layer", "mode"],
)

context_rag_hit = Gauge(
    "context_rag_hit_count",
    "RAG hit count by kind",
    ["kind"],
)

context_rag_build_ms = Gauge(
    "context_rag_build_ms",
    "RAG retrieval build time in milliseconds",
    [],
)

context_tools_injected = Gauge(
    "context_tools_injected",
    "Number of tool schemas injected this turn",
    ["mode"],
)

context_compaction = Gauge(
    "context_compaction_rate",
    "Compaction triggered this turn (1 = compacted)",
    ["mode"],
)

context_token_budget = Gauge(
    "context_token_budget_allocated",
    "Tokens allocated across layers",
    ["layer"],
)

context_token_ratio = Gauge(
    "context_token_budget_usage_ratio",
    "Ratio of used tokens vs max_total",
    ["tenant_id", "mode"],
)

context_dlp_blocks = Counter(
    "context_dlp_blocks_total",
    "DLP blocked turns",
    ["tenant_id"],
)


# ═══════════════════════════════════════════════════════════════
# Emission helpers
# ═══════════════════════════════════════════════════════════════

def emit_step_metrics(state: ContextState) -> None:
    """Emit metrics from the completed ContextState.

    Called after assemble_context() returns.
    """
    if not _PROMETHEUS_AVAILABLE:
        return

    tenant_id = state.tenant_id
    mode = state.mode
    role = state.role

    # Build duration
    context_build_duration.labels(
        tenant_id=tenant_id, mode=mode, role=role,
    ).observe(state.build_ms)

    # Step durations
    for key, value in state.meta.items():
        if key.startswith("step_ms."):
            step_name = key.replace("step_ms.", "")
            # Infer phase from step name
            phase = step_name.split(".")[0] if "." in step_name else "unknown"
            context_step_duration.labels(
                tenant_id=tenant_id, step=step_name, phase=phase,
            ).observe(value)

    # Step errors
    for step_name in state.meta.get("step_errors", []):
        context_step_errors.labels(step=step_name).inc()

    # Layers applied
    for layer in state.layers_applied:
        context_layers_applied.labels(layer=layer, mode=mode).set(1)

    # RAG hits
    for kind, count in state.meta.get("rag_hit_count", {}).items():
        context_rag_hit.labels(kind=kind).set(count)

    # RAG build time
    if "rag_build_ms" in state.meta:
        context_rag_build_ms.set(state.meta["rag_build_ms"])

    # Tools
    context_tools_injected.labels(mode=mode).set(len(state.tools))

    # Compaction
    context_compaction.labels(mode=mode).set(
        1 if state.session_truncated else 0
    )

    # Token budget
    budget = state.meta.get("token_budget", {})
    for layer_name in ("l0_l4", "l5_rag", "l6_window", "l7_tools"):
        context_token_budget.labels(layer=layer_name).set(
            budget.get(layer_name, 0)
        )

    # Token ratio
    max_total = budget.get("max_total", 128_000)
    used = sum(budget.get(k, 0) for k in ("l0_l4", "l5_rag", "l6_window", "l7_tools"))
    ratio = used / max(max_total, 1)
    context_token_ratio.labels(tenant_id=tenant_id, mode=mode).set(ratio)

    # DLP
    if state.meta.get("dlp_blocked"):
        context_dlp_blocks.labels(tenant_id=tenant_id).inc()

    logger.debug(
        "metrics emitted request_id=%s build_ms=%.1f steps=%d tools=%d",
        state.request_id, state.build_ms, len(state.layers_applied), len(state.tools),
    )
