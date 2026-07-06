"""Testes para stack_health (P0-10)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.stack_health import _probe_health_url, collect_central_stack_health


class TestProbeHealthUrl(unittest.TestCase):
    def test_first_path_2xx(self) -> None:
        with patch("app.stack_health.httpx.Client") as mc:
            inst = MagicMock()
            inst.get.return_value.status_code = 200
            cm = MagicMock()
            cm.__enter__.return_value = inst
            cm.__exit__.return_value = False
            mc.return_value = cm
            out = _probe_health_url("http://svc", ("/health",), 2.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["health_path"], "/health")

    def test_fallback_second_path(self) -> None:
        with patch("app.stack_health.httpx.Client") as mc:
            inst = MagicMock()
            r404 = MagicMock()
            r404.status_code = 404
            r200 = MagicMock()
            r200.status_code = 200
            inst.get.side_effect = [r404, r200]
            cm = MagicMock()
            cm.__enter__.return_value = inst
            cm.__exit__.return_value = False
            mc.return_value = cm
            out = _probe_health_url("http://prom", ("/-/healthy", "/health"), 2.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["health_path"], "/health")


class TestCollectCentralStackHealth(unittest.TestCase):
    @patch("app.stack_health.httpx.Client")
    def test_summary_shape(self, mc: MagicMock) -> None:
        inst = MagicMock()
        inst.get.return_value.status_code = 200
        cm = MagicMock()
        cm.__enter__.return_value = inst
        cm.__exit__.return_value = False
        mc.return_value = cm

        with patch.multiple(
            "app.stack_health",
            MODEL_ROUTER_URL="http://mr",
            SYSTEM_AGENT_URL="http://sa",
            KERNEL_OBSERVER_URL="http://ko",
            stack_health_stt_entry=lambda: {"status": "disabled"},
            LLM_SERVICE_URL="http://llm",
            DISABLE_LLM_SERVICE=False,
            stack_health_tts_entry=lambda: {"status": "disabled"},
            PROMETHEUS_URL="http://prom",
            MEMORY_ENABLED=True,
            MEMORY_DB_URL="postgresql://x",
            STACK_HEALTH_PROBE_TIMEOUT=2.0,
        ):
            out = collect_central_stack_health("rid-x")

        self.assertEqual(out["request_id"], "rid-x")
        self.assertEqual(out["services"]["stt"]["status"], "disabled")
        self.assertEqual(out["services"]["tts"]["status"], "disabled")
        self.assertGreaterEqual(out["summary"]["ok"], 1)
        self.assertGreaterEqual(out["summary"]["disabled"], 2)
        self.assertIn("memory_db", out["services"])


if __name__ == "__main__":
    unittest.main()
