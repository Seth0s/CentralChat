"""Classificacao request_shell."""
from __future__ import annotations

import unittest

from app.shell_request_policy import classify_shell_request


class TestShellRequestPolicy(unittest.TestCase):
    def test_sh_c_always_p3(self) -> None:
        clf, err = classify_shell_request(
            mode="sh_c",
            argv=None,
            sh_c="ls -la",
            cwd="/tmp",
            shell_session_id=None,
            intent="listar",
            timeout_sec=10,
            request_id="r1",
        )
        self.assertIsNone(err)
        assert clf is not None
        self.assertEqual(clf.risk, "P3")
        self.assertEqual(clf.gateway_body.get("mode"), "sh_c")

    def test_argv_p0_ls(self) -> None:
        clf, err = classify_shell_request(
            mode="argv",
            argv=["ls", "/central"],
            sh_c=None,
            cwd="/central",
            shell_session_id=None,
            intent="ver ficheiros",
            timeout_sec=None,
            request_id="r2",
        )
        self.assertIsNone(err)
        assert clf is not None
        self.assertEqual(clf.risk, "P0")

    def test_argv_unknown_goes_p3(self) -> None:
        clf, err = classify_shell_request(
            mode="argv",
            argv=["docker", "ps"],
            sh_c=None,
            cwd=None,
            shell_session_id=None,
            intent="containers",
            timeout_sec=None,
            request_id="r3",
        )
        self.assertIsNone(err)
        assert clf is not None
        self.assertEqual(clf.risk, "P3")
        self.assertEqual(clf.reason, "unknown_binary_queue")

    def test_elevation_rejected(self) -> None:
        _, err = classify_shell_request(
            mode="argv",
            argv=["sudo", "ls"],
            sh_c=None,
            cwd=None,
            shell_session_id=None,
            intent="x",
            timeout_sec=None,
            request_id="r4",
        )
        self.assertEqual(err, "elevation_forbidden")


if __name__ == "__main__":
    unittest.main()
