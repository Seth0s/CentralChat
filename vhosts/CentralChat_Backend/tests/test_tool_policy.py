"""ADR17-1 — tool_policy.classify_tool_call."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.tool_policy import classify_tool_call
from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_REQUEST_SHELL


class TestToolPolicy(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    def test_platform_denied(self) -> None:
        r = classify_tool_call(TOOL_NAME_GET_HOST_SUMMARY, {}, "t1")
        self.assertFalse(r.allowed)
        self.assertEqual(r.error_code, "platform_tool_disabled")

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
    def test_platform_allowed_when_legacy(self) -> None:
        r = classify_tool_call(TOOL_NAME_GET_HOST_SUMMARY, {}, "t1")
        self.assertTrue(r.allowed)

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.tool_policy.connector_online_for_tenant", return_value=True)
    def test_client_allowed(self, _online: unittest.mock.MagicMock) -> None:
        r = classify_tool_call(TOOL_NAME_REQUEST_SHELL, {"intent": "x"}, "t1")
        self.assertTrue(r.allowed)

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.tool_policy.connector_online_for_tenant", return_value=False)
    def test_client_offline_denied(self, _online: unittest.mock.MagicMock) -> None:
        r = classify_tool_call(TOOL_NAME_REQUEST_SHELL, {"intent": "x"}, "t1")
        self.assertFalse(r.allowed)
        self.assertEqual(r.error_code, "client_agent_offline")


if __name__ == "__main__":
    unittest.main()
