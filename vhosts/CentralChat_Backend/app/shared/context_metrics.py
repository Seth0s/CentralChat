"""Prometheus metrics for the context system (Phase 8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from app.context import TokenAccounting

CONTEXT_TOKENS = Histogram(
    "central_context_tokens",
    "Estimated prompt tokens per section (assembler)",
    ["section"],
    buckets=(0.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0, 8192.0, 16384.0, 32768.0, 65536.0, 131072.0),
)

COMPACTION_RUNS_TOTAL = Counter(
    "central_compaction_runs_total",
    "CompactionService runs",
    ["mode"],
)

RAG_HITS_TOTAL = Counter(
    "central_rag_hits_total",
    "RAG retrieval hits injected into prompt",
    ["namespace"],
)


def record_context_tokens(accounting: TokenAccounting | None) -> None:
    if accounting is None:
        return
    try:
        CONTEXT_TOKENS.labels(section="verbatim").observe(float(accounting.verbatim_tokens))
        for section, count in (accounting.section_tokens or {}).items():
            if count:
                CONTEXT_TOKENS.labels(section=str(section)[:64]).observe(float(count))
        total = accounting.total_estimated_tokens
        if total is not None:
            CONTEXT_TOKENS.labels(section="total").observe(float(total))
    except Exception:
        pass


def record_compaction_run(*, mode: str) -> None:
    try:
        COMPACTION_RUNS_TOTAL.labels(mode=(mode or "unknown")[:32]).inc()
    except Exception:
        pass


def record_rag_hits(*, namespace: str, count: int) -> None:
    if count <= 0:
        return
    try:
        RAG_HITS_TOTAL.labels(namespace=(namespace or "unknown")[:32]).inc(int(count))
    except Exception:
        pass
