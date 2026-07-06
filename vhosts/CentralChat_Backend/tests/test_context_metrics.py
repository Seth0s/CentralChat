"""Phase 8 — context Prometheus metrics."""
from __future__ import annotations

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock

_orig_prometheus: object | None = None


def setUpModule() -> None:
    global _orig_prometheus
    _orig_prometheus = sys.modules.get("prometheus_client")
    stub = ModuleType("prometheus_client")

    def _counter(*_a: object, **_k: object) -> MagicMock:
        m = MagicMock()
        m.labels.return_value = m
        return m

    def _histogram(*_a: object, **_k: object) -> MagicMock:
        m = MagicMock()
        m.labels.return_value = m
        return m

    stub.Counter = _counter
    stub.Histogram = _histogram
    sys.modules["prometheus_client"] = stub
    import importlib

    import app.context_metrics as cm

    importlib.reload(cm)


def tearDownModule() -> None:
    if _orig_prometheus is not None:
        sys.modules["prometheus_client"] = _orig_prometheus  # type: ignore[assignment]
    else:
        sys.modules.pop("prometheus_client", None)


class TestContextMetrics(unittest.TestCase):
    def test_record_rag_hits_increments(self) -> None:
        from app.context_metrics import RAG_HITS_TOTAL, record_rag_hits

        record_rag_hits(namespace="product", count=3)
        RAG_HITS_TOTAL.labels.assert_called_with(namespace="product")

    def test_record_compaction_run(self) -> None:
        from app.context_metrics import record_compaction_run

        record_compaction_run(mode="sync")


if __name__ == "__main__":
    unittest.main()
