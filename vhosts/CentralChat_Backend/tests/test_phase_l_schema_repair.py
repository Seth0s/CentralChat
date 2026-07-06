"""L1-4 — reparacao de schema quando validate_tool_arguments falha."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.tool_loop import run_agent_tool_flow
from app.tool_registry import TOOL_NAME_LIST_PROCESSES


class TestPhaseLSchemaRepair(unittest.TestCase):
    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_schema_repair_then_dispatch(self, mock_llm, mock_dispatch) -> None:
        bad = (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {"limit": 400}}]}'
            % TOOL_NAME_LIST_PROCESSES
        )
        good = (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {"limit": 20}}]}'
            % TOOL_NAME_LIST_PROCESSES
        )
        mock_llm.side_effect = [bad, good, '{"final": "Lista resumida.", "tool_calls": []}']
        mock_dispatch.return_value = {"ok": True, "pids": []}
        from app import tool_loop as tl

        with patch.object(tl, "AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 1):
            reply, meta = run_agent_tool_flow(
                user_text="processos?",
                base_history=[],
                request_id="l-sr-1",
                profile="balanced",
                max_tool_executions=1,
                audit=None,
            )
        self.assertEqual(reply, "Lista resumida.")
        self.assertEqual(meta.get("tools_run"), 1)
        self.assertEqual(meta.get("json_schema_repair_extra_calls"), 1)
        mock_dispatch.assert_called_once()
        pos = mock_dispatch.call_args[0]
        self.assertEqual(pos[0], TOOL_NAME_LIST_PROCESSES)
        self.assertEqual(pos[1], {"limit": 20})

    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_no_schema_repair_when_disabled(self, mock_llm, mock_dispatch) -> None:
        bad = (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {"limit": 400}}]}'
            % TOOL_NAME_LIST_PROCESSES
        )
        mock_llm.return_value = bad
        from app import tool_loop as tl

        with patch.object(tl, "AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0):
            reply, meta = run_agent_tool_flow(
                user_text="x",
                base_history=[],
                request_id="l-sr-2",
                profile="balanced",
                max_tool_executions=1,
                audit=None,
            )
        self.assertIn("argumentos", reply.lower())
        self.assertEqual(meta.get("mode"), "tool_arguments_invalid")
        self.assertEqual(meta.get("json_schema_repair_extra_calls"), 0)
        mock_dispatch.assert_not_called()
        mock_llm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
