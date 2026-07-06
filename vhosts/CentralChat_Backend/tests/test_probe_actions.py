"""P1 Onda 4 — allowlist e validacao de network.endpoint.probe."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

import app.probe_actions as pa


class TestProbeAllowlist(unittest.TestCase):
    def test_parse_host_port(self) -> None:
        self.assertEqual(pa.parse_host_port_token("127.0.0.1:8004"), ("127.0.0.1", 8004))
        self.assertEqual(pa.parse_host_port_token(" model-router:8005 "), ("model-router", 8005))
        self.assertEqual(pa.parse_host_port_token("[::1]:8080"), ("::1", 8080))
        self.assertIsNone(pa.parse_host_port_token("nocolon"))
        self.assertIsNone(pa.parse_host_port_token(""))

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "example.com:443,127.0.0.1:53")
    def test_endpoint_allowed(self) -> None:
        self.assertTrue(pa.endpoint_allowed("Example.COM", 443))
        self.assertTrue(pa.endpoint_allowed("127.0.0.1", 53))
        self.assertFalse(pa.endpoint_allowed("evil.com", 443))

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "")
    def test_empty_allowlist_denies(self) -> None:
        ok, code, _ = pa.validate_probe_for_queue("127.0.0.1", 80, "tcp", None)
        self.assertFalse(ok)
        self.assertEqual(code, "probe_allowlist_not_configured")

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:80")
    def test_tcp_no_path(self) -> None:
        ok, err, store = pa.validate_probe_for_queue("127.0.0.1", 80, "tcp", None)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(store["kind"], "tcp")
        self.assertNotIn("path", store)

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:80")
    def test_tcp_rejects_path(self) -> None:
        ok, code, _ = pa.validate_probe_for_queue("127.0.0.1", 80, "tcp", "/x")
        self.assertFalse(ok)
        self.assertEqual(code, "probe_path_not_allowed_for_tcp")

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:8080")
    def test_http_default_path(self) -> None:
        ok, _, store = pa.validate_probe_for_queue("127.0.0.1", 8080, "http", None)
        self.assertTrue(ok)
        self.assertEqual(store["path"], "/")

    @patch.object(pa, "PROBE_HTTP_PATH_ALLOWLIST_RAW", "/,/health")
    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:8080")
    def test_http_path_allowlist(self) -> None:
        ok, _, store = pa.validate_probe_for_queue("127.0.0.1", 8080, "http", "/health")
        self.assertTrue(ok)
        self.assertEqual(store["path"], "/health")
        ok2, code2, _ = pa.validate_probe_for_queue("127.0.0.1", 8080, "http", "/admin")
        self.assertFalse(ok2)
        self.assertEqual(code2, "probe_http_path_not_allowlisted")


class TestRunNetworkProbe(unittest.TestCase):
    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:9")
    @patch.object(pa, "PROBE_TIMEOUT_SEC", 1.0)
    @patch("app.probe_actions.socket.create_connection")
    def test_tcp_ok(self, mock_conn) -> None:
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = MagicMock()
        mock_cm.__exit__.return_value = False
        mock_conn.return_value = mock_cm
        out = pa.run_network_probe({"host": "127.0.0.1", "port": 9, "kind": "tcp"})
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("probe_ok"))

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:9")
    @patch.object(pa, "PROBE_TIMEOUT_SEC", 1.0)
    @patch("app.probe_actions.httpx.Client")
    def test_http_ok(self, mock_client_cls) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_inner = MagicMock()
        mock_inner.get.return_value = mock_resp
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_inner
        mock_ctx.__exit__.return_value = False
        mock_client_cls.return_value = mock_ctx
        out = pa.run_network_probe({"host": "127.0.0.1", "port": 9, "kind": "http", "path": "/health"})
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("probe_ok"))
        self.assertEqual(out.get("http_status"), 200)

    @patch.object(pa, "PROBE_ALLOWLIST_RAW", "127.0.0.1:9")
    @patch.object(pa, "PROBE_TIMEOUT_SEC", 1.0)
    @patch("app.probe_actions.httpx.Client")
    def test_http_error(self, mock_client_cls) -> None:
        mock_inner = MagicMock()
        mock_inner.get.side_effect = httpx.ConnectError("fail", request=MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_inner
        mock_ctx.__exit__.return_value = False
        mock_client_cls.return_value = mock_ctx
        out = pa.run_network_probe({"host": "127.0.0.1", "port": 9, "kind": "http", "path": "/"})
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("probe_ok"))


if __name__ == "__main__":
    unittest.main()
