"""OC-12 — allowlist e POST /dev/web-fetch (ADR-010)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.web_fetch_dev import fetch_web_dev, parse_host_allowlist, validate_url_for_allowlist


class TestWebFetchAllowlist(unittest.TestCase):
    def test_parse_allowlist(self) -> None:
        s = parse_host_allowlist("Example.COM, ,foo.test")
        self.assertEqual(s, frozenset({"example.com", "foo.test"}))

    def test_validate_ok(self) -> None:
        allow = frozenset({"example.org"})
        validate_url_for_allowlist("https://example.org/path", allow)

    def test_validate_rejects_host(self) -> None:
        allow = frozenset({"example.org"})
        with self.assertRaises(ValueError):
            validate_url_for_allowlist("https://evil.com/", allow)

    def test_fetch_uses_get_no_redirects(self) -> None:
        allow = frozenset({"httpbin.org"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"hello"
        mock_resp.headers = {"content-type": "text/plain; charset=utf-8"}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        out = fetch_web_dev(
            "https://httpbin.org/get",
            allow_hosts=allow,
            max_bytes=100,
            timeout=5.0,
            client=mock_client,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "hello")
        mock_client.get.assert_called_once()
        mock_client.close.assert_not_called()


class TestDevWebFetchRoute(unittest.TestCase):
    def setUp(self) -> None:
        from app.server import app

        self.client = TestClient(app)

    def test_disabled_404(self) -> None:
        with patch("app.server.WEB_FETCH_MVP_ENABLED", False):
            r = self.client.post("/dev/web-fetch", json={"url": "https://example.com/"})
        self.assertEqual(r.status_code, 404)

    def test_enabled_bad_host_400(self) -> None:
        with patch("app.server.WEB_FETCH_MVP_ENABLED", True):
            with patch("app.server.WEB_FETCH_ALLOWLIST_HOSTS_RAW", "example.org"):
                with patch("app.server.WEB_FETCH_MAX_BYTES", 1024):
                    with patch("app.server.WEB_FETCH_TIMEOUT_SEC", 5.0):
                        r = self.client.post("/dev/web-fetch", json={"url": "https://evil.com/x"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
