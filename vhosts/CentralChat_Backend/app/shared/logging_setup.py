"""Evita poluir stdout com GET /metrics (scrape do Prometheus)."""
from __future__ import annotations

import logging


def suppress_metrics_access_log() -> None:
    class _Filter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "/metrics" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_Filter())
