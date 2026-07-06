"""P1 Onda 1 — validacao desktop.open_url / desktop.notify e helper (mock)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import app.desktop_actions as da


class TestOpenUrlValidation(unittest.TestCase):
    def setUp(self) -> None:
        self._p = patch.object(da, "OPEN_URL_ALLOW_HTTP", False)
        self._p.start()
        self._p2 = patch.object(da, "OPEN_URL_MAX_LEN", 2048)
        self._p2.start()

    def tearDown(self) -> None:
        self._p2.stop()
        self._p.stop()

    def test_https_example_allowlisted(self) -> None:
        with patch.object(da, "OPEN_URL_HOST_ALLOWLIST_RAW", "example.com"):
            ok, err, norm = da.validate_open_url_for_queue("  https://example.com/path  ")
            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertEqual(norm, "https://example.com/path")

    def test_suffix_allowlist(self) -> None:
        with patch.object(da, "OPEN_URL_HOST_ALLOWLIST_RAW", ".github.com"):
            ok, _, _ = da.validate_open_url_for_queue("https://api.github.com/foo")
            self.assertTrue(ok)

    def test_reject_without_allowlist(self) -> None:
        with patch.object(da, "OPEN_URL_HOST_ALLOWLIST_RAW", ""):
            ok, code, _ = da.validate_open_url_for_queue("https://example.com/")
            self.assertFalse(ok)
            self.assertEqual(code, "open_url_allowlist_not_configured")

    def test_reject_javascript_scheme(self) -> None:
        with patch.object(da, "OPEN_URL_HOST_ALLOWLIST_RAW", "evil.com"):
            ok, code, _ = da.validate_open_url_for_queue("javascript:alert(1)")
            self.assertFalse(ok)
            self.assertEqual(code, "url_scheme_not_allowed")

    def test_reject_userinfo(self) -> None:
        with patch.object(da, "OPEN_URL_HOST_ALLOWLIST_RAW", "example.com"):
            ok, code, _ = da.validate_open_url_for_queue("https://user:pass@example.com/")
            self.assertFalse(ok)
            self.assertEqual(code, "url_userinfo_not_allowed")


class TestNotifyValidation(unittest.TestCase):
    def test_ok_body_only(self) -> None:
        ok, err, store = da.validate_notify_for_queue("  Hello world  ", None)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(store["body"], "Hello world")
        self.assertEqual(store["urgency"], "low")
        self.assertNotIn("title", store)

    def test_reject_htmlish(self) -> None:
        ok, code, _ = da.validate_notify_for_queue("<b>x</b>", None)
        self.assertFalse(ok)
        self.assertEqual(code, "invalid_notify_body")


class TestDesktopHelper(unittest.TestCase):
    @patch.object(da, "DESKTOP_HELPER_PATH", "")
    def test_missing_helper_config(self) -> None:
        out = da.run_desktop_helper("open_url", {"url": "https://example.com"})
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "desktop_helper_not_configured")

    @patch.object(da, "DESKTOP_HELPER_PATH", "/bin/true")
    @patch.object(da, "DESKTOP_HELPER_TIMEOUT_SEC", 5.0)
    @patch("app.desktop_actions.subprocess.run")
    @patch("app.desktop_actions.os.path.isfile", return_value=True)
    @patch("app.desktop_actions.os.access", return_value=True)
    def test_subprocess_invoked(self, _acc, _isf, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        out = da.run_desktop_helper("notify", {"title": "T", "body": "B", "urgency": "low"})
        self.assertTrue(out.get("ok"))
        mock_run.assert_called_once()
        call_kw = mock_run.call_args.kwargs
        self.assertIn("input", call_kw)
        stdin_obj = json.loads(call_kw["input"].decode("utf-8"))
        self.assertEqual(stdin_obj.get("op"), "notify")
        self.assertEqual(stdin_obj.get("body"), "B")


if __name__ == "__main__":
    unittest.main()
