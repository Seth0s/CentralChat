"""Onda D — ops, metrics, deploy helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.shared.business_metrics import (
    APPROVALS_TOTAL,
    POLICY_VIOLATIONS_TOTAL,
    STREAMS_TOTAL,
    inc_approval,
    inc_policy_violation,
    refresh_siem_dead_gauge,
    stream_finished,
)
from app.shared.alerting import send_ops_alert
from app.tenant_quota import get_usage_summary_24h


class OndaDMetricsTest(unittest.TestCase):
    def test_inc_approval(self) -> None:
        before = APPROVALS_TOTAL.labels(resolution="approved")._value.get()  # type: ignore[attr-defined]
        inc_approval("approved")
        after = APPROVALS_TOTAL.labels(resolution="approved")._value.get()  # type: ignore[attr-defined]
        self.assertGreater(after, before)

    def test_policy_violation_counter(self) -> None:
        before = POLICY_VIOLATIONS_TOTAL.labels(error_code="test")._value.get()  # type: ignore[attr-defined]
        inc_policy_violation("test")
        after = POLICY_VIOLATIONS_TOTAL.labels(error_code="test")._value.get()  # type: ignore[attr-defined]
        self.assertGreater(after, before)

    def test_stream_finished(self) -> None:
        before = STREAMS_TOTAL.labels(status="ok")._value.get()  # type: ignore[attr-defined]
        stream_finished(ok=True)
        after = STREAMS_TOTAL.labels(status="ok")._value.get()  # type: ignore[attr-defined]
        self.assertGreater(after, before)

    def test_siem_dead_gauge(self) -> None:
        refresh_siem_dead_gauge(3)
        # gauge set — no exception


class OndaDUsageTest(unittest.TestCase):
    @patch("app.tenant_quota.memory_db_enabled", return_value=False)
    def test_usage_window_in_response(self, *_m: object) -> None:
        out = get_usage_summary_24h(window="7d")
        self.assertEqual(out["window"], "7d")


class OndaDAlertingTest(unittest.TestCase):
    @patch("app.shared.alerting.httpx.post")
    @patch("app.shared.alerting.CENTRAL_ALERT_WEBHOOK_URL", "http://example.invalid/hook")
    def test_send_ops_alert(self, mock_post: object) -> None:
        send_ops_alert(action="test", text="hello")
        import time

        time.sleep(0.2)


class OndaDAuditFilterTest(unittest.TestCase):
    @patch("app.audit_service.memory_db_enabled", return_value=False)
    def test_list_with_path_prefix_no_db(self, *_m: object) -> None:
        from app.audit_service import list_audit_events

        self.assertEqual(list_audit_events(path_prefix="payment/"), [])


if __name__ == "__main__":
    unittest.main()
