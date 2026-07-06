"""Fase L — re-prompt de reparacao quando o primeiro output nao e JSON valido."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.tool_loop import run_agent_tool_flow
from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY


class TestPhaseLJsonRepair(unittest.TestCase):
    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_repair_second_call_yields_valid_json(self, mock_llm, mock_dispatch) -> None:
        mock_llm.side_effect = [
            "Desculpa, aqui esta a analise em texto livre sem JSON.",
            '{"final": "Agora sim, JSON valido.", "tool_calls": []}',
        ]
        reply, meta = run_agent_tool_flow(
            user_text="pergunta",
            base_history=[],
            request_id="l-1",
            profile="balanced",
            max_tool_executions=1,
            audit=None,
        )
        self.assertEqual(reply, "Agora sim, JSON valido.")
        self.assertEqual(meta.get("mode"), "final_direct")
        self.assertTrue(meta.get("json_parse_ok"))
        self.assertEqual(meta.get("json_repair_extra_calls"), 1)
        mock_dispatch.assert_not_called()

    def test_no_repair_when_disabled_by_zero_extra(self) -> None:
        from app import tool_loop as tl

        with patch.object(tl, "AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0), patch.object(
            tl, "call_llm", return_value="ainda nao e json"
        ) as mock_llm, patch.object(tl, "dispatch_tool") as mock_dispatch:
            reply, meta = run_agent_tool_flow(
                user_text="x",
                base_history=[],
                request_id="l-2",
                profile="balanced",
                max_tool_executions=1,
                audit=None,
            )
        self.assertEqual(reply, "ainda nao e json")
        self.assertEqual(meta.get("mode"), "plain_text_no_json")
        self.assertFalse(meta.get("json_parse_ok"))
        self.assertEqual(meta.get("json_repair_extra_calls"), 0)
        mock_llm.assert_called_once()

    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_repair_then_tool_dispatch(self, mock_llm, mock_dispatch) -> None:
        mock_llm.side_effect = [
            "oops texto",
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}' % TOOL_NAME_GET_HOST_SUMMARY,
            '{"final": "Feito.", "tool_calls": []}',
        ]
        mock_dispatch.return_value = {"ok": True}
        reply, meta = run_agent_tool_flow(
            user_text="cpu?",
            base_history=[],
            request_id="l-3",
            profile="balanced",
            max_tool_executions=1,
            audit=None,
        )
        self.assertEqual(reply, "Feito.")
        self.assertEqual(meta.get("tools_run"), 1)
        self.assertGreaterEqual(meta.get("json_repair_extra_calls", 0), 1)
        mock_dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
