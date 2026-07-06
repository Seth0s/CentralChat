"""F3/A5 — ponte user pós-TOOL_RESULT por família."""
from __future__ import annotations

import unittest

import app.tool_registry as tool_registry
from app.post_tool_bridge import post_tool_user_prompt
from app.tool_registry import (
    TOOL_NAME_APPLY_CANVAS_PATCH,
    TOOL_NAME_CREATE_APPROVAL_REQUEST,
    TOOL_NAME_GET_HOST_SUMMARY,
    TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT,
    TOOL_NAME_REQUEST_SHELL,
)


class TestPostToolBridge(unittest.TestCase):
    def test_read_host_mentions_cpu(self) -> None:
        s = post_tool_user_prompt(TOOL_NAME_GET_HOST_SUMMARY)
        self.assertIn("CPU", s)
        self.assertIn("TOOL_RESULT", s)

    def test_canvas_mentions_workspace(self) -> None:
        s = post_tool_user_prompt(TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT)
        self.assertIn("workspace", s.lower())
        s2 = post_tool_user_prompt(TOOL_NAME_APPLY_CANVAS_PATCH)
        self.assertIn("canvas", s2.lower())

    def test_shell_mentions_shell(self) -> None:
        s = post_tool_user_prompt(TOOL_NAME_REQUEST_SHELL)
        self.assertIn("shell", s.lower())

    def test_generic_approval(self) -> None:
        s = post_tool_user_prompt(TOOL_NAME_CREATE_APPROVAL_REQUEST)
        self.assertIn("approval", s.lower())

    def test_every_registered_tool_returns_non_empty_bridge(self) -> None:
        for name in tool_registry._TOOL_SPECS:
            with self.subTest(tool=name):
                out = post_tool_user_prompt(name)
                self.assertGreaterEqual(len(out), 40, name)


if __name__ == "__main__":
    unittest.main()
