"""Fase I — métricas espelham eventos de audit do tool loop.

Stub de prometheus_client só durante este módulo (setUpModule/tearDownModule)
para não poluir sys.modules e quebrar imports de Gauge noutros testes.
"""
from __future__ import annotations

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock

_orig_prometheus_client: object | None = None
agent_tool_metrics: object | None = None


def _metric_factory(*_a, **_kw):
    m = MagicMock()
    m.labels = MagicMock(return_value=MagicMock(inc=MagicMock(), observe=MagicMock()))
    return m


def setUpModule() -> None:
    global _orig_prometheus_client, agent_tool_metrics
    _orig_prometheus_client = sys.modules.get("prometheus_client")
    stub = ModuleType("prometheus_client")
    stub.Counter = _metric_factory
    stub.Histogram = _metric_factory
    stub.Gauge = _metric_factory
    stub.generate_latest = MagicMock(return_value=b"# EOF\n")
    stub.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    sys.modules["prometheus_client"] = stub
    sys.modules.pop("app.agent_tool_metrics", None)
    import app.agent_tool_metrics as _atm

    agent_tool_metrics = _atm


def tearDownModule() -> None:
    global _orig_prometheus_client, agent_tool_metrics
    if _orig_prometheus_client is not None:
        sys.modules["prometheus_client"] = _orig_prometheus_client  # type: ignore[assignment]
    else:
        sys.modules.pop("prometheus_client", None)
    sys.modules.pop("app.agent_tool_metrics", None)
    agent_tool_metrics = None
    _orig_prometheus_client = None


class TestAgentToolMetrics(unittest.TestCase):
    def setUp(self) -> None:
        assert agent_tool_metrics is not None
        agent_tool_metrics.TOOL_DENIED_TOTAL.reset_mock()
        agent_tool_metrics.TOOL_INVOKED_TOTAL.reset_mock()
        agent_tool_metrics.TOOL_EXECUTION_OK_TOTAL.reset_mock()
        agent_tool_metrics.TOOL_DENIED_DIGEST_CONTEXT_TOTAL.reset_mock()

    def test_denied_unknown_increments(self) -> None:
        assert agent_tool_metrics is not None
        agent_tool_metrics.record_agent_tool_audit_event(
            {"event": "tool_denied", "reason": "unknown_or_disallowed_tool", "tool": "x"}
        )
        agent_tool_metrics.TOOL_DENIED_TOTAL.labels.assert_called_with(reason="unknown_tool")
        agent_tool_metrics.TOOL_DENIED_TOTAL.labels.return_value.inc.assert_called_once()
        agent_tool_metrics.TOOL_DENIED_DIGEST_CONTEXT_TOTAL.labels.assert_called_with(
            reason="unknown_tool", digest_in_prompt="false"
        )

    def test_denied_invalid_args_increments(self) -> None:
        assert agent_tool_metrics is not None
        agent_tool_metrics.record_agent_tool_audit_event(
            {"event": "tool_denied", "reason": "invalid_arguments"}
        )
        agent_tool_metrics.TOOL_DENIED_TOTAL.labels.assert_called_with(reason="invalid_arguments")

    def test_denied_with_digest_flag(self) -> None:
        assert agent_tool_metrics is not None
        agent_tool_metrics.record_agent_tool_audit_event(
            {
                "event": "tool_denied",
                "reason": "invalid_arguments",
                "capability_digest_in_prompt": True,
            }
        )
        agent_tool_metrics.TOOL_DENIED_DIGEST_CONTEXT_TOTAL.labels.assert_called_with(
            reason="invalid_arguments", digest_in_prompt="true"
        )

    def test_invoked_and_ok(self) -> None:
        assert agent_tool_metrics is not None
        agent_tool_metrics.record_agent_tool_audit_event({"event": "tool_invoked", "tool": "get_host_summary"})
        agent_tool_metrics.TOOL_INVOKED_TOTAL.labels.assert_called_with(tool="get_host_summary")
        agent_tool_metrics.record_agent_tool_audit_event({"event": "tool_result_ok", "tool": "get_host_summary"})
        agent_tool_metrics.TOOL_EXECUTION_OK_TOTAL.labels.assert_called_with(tool="get_host_summary")


if __name__ == "__main__":
    unittest.main()
