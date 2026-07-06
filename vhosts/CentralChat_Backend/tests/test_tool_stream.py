"""SSE agent-tools: iter_agent_tool_stream."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.tool_loop import iter_agent_tool_stream
from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY

from tests.stream_ndjson_utils import make_ndjson_side_effect


class TestToolStream(unittest.TestCase):
    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_tool_then_final_emits_proposed_result_tokens(self, mock_llm, mock_dispatch):
        streams = [
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY,
            '{"final": "Resumo: CPU moderada.", "tool_calls": []}',
        ]
        mock_dispatch.return_value = {"cpu": {"usage_pct": 12}}
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="Como está o CPU?",
                    base_history=[],
                    request_id="r1",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=10,
                )
            )

        kinds = [e[0] for e in events]
        self.assertIn("tool_proposed", kinds)
        self.assertIn("tool_running", kinds)
        self.assertIn("tool_result", kinds)
        self.assertLess(kinds.index("tool_proposed"), kinds.index("tool_running"))
        self.assertLess(kinds.index("tool_running"), kinds.index("tool_result"))
        tr = next(e for e in events if e[0] == "tool_result")
        self.assertTrue(tr[1].get("ok"))
        self.assertGreater(kinds.count("token"), 0)
        self.assertEqual(meta.get("reply"), "Resumo: CPU moderada.")
        self.assertEqual(meta.get("tools_run"), 1)
        mock_dispatch.assert_called_once()

    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_final_before_tool_then_final_in_reply(self, mock_llm, mock_dispatch):
        streams = [
            '{"final": "Vou consultar o host.", "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY,
            '{"final": "CPU moderada.", "tool_calls": []}',
        ]
        mock_dispatch.return_value = {"cpu": {"usage_pct": 12}}
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="CPU?",
                    base_history=[],
                    request_id="r-preamble",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        kinds = [e[0] for e in events]
        tp = kinds.index("tool_proposed")
        self.assertGreater(tp, 0)
        self.assertEqual(kinds[tp - 1], "token")
        token_payload = "".join(e[1].get("d", "") for e in events if e[0] == "token")
        self.assertIn("Vou consultar o host.", token_payload)
        self.assertIn("CPU moderada.", token_payload)
        self.assertEqual(
            meta.get("reply"),
            "Vou consultar o host.\n\nCPU moderada.",
        )

    @patch("app.tool_loop.call_llm")
    def test_unknown_tool_yields_denied_and_message(self, mock_llm):
        streams = [
            '{"final": null, "tool_calls": [{"name": "tool_inventada", "arguments": {}}]}',
        ]
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="x",
                    base_history=[],
                    request_id="r2",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        self.assertTrue(any(e[0] == "tool_denied" for e in events))
        self.assertTrue(any(e[0] == "token" for e in events))
        self.assertIn("PROTOCOLO_AGENT_TOOLS", meta.get("reply", ""))

    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_tool_result_ok_false_when_dispatch_returns_error(self, mock_llm, mock_dispatch):
        streams = [
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY,
            '{"final": "Erro ao ler host.", "tool_calls": []}',
        ]
        mock_dispatch.return_value = {"ok": False, "error": "shell_gateway_not_configured"}
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="x",
                    base_history=[],
                    request_id="r3",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        tr = next(e for e in events if e[0] == "tool_result")
        self.assertFalse(tr[1].get("ok"))

    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.call_llm")
    def test_workspace_store_key_passed_to_dispatch(self, mock_llm, mock_dispatch):
        streams = [
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY,
            '{"final": "Ok.", "tool_calls": []}',
        ]
        mock_dispatch.return_value = {"cpu": {"usage_pct": 1}}
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            list(
                iter_agent_tool_stream(
                    user_text="q",
                    base_history=[],
                    request_id="http-req-zz",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                    workspace_store_key="stable-ws-session-99",
                )
            )
        mock_dispatch.assert_called_once()
        _args, kwargs = mock_dispatch.call_args
        self.assertEqual(kwargs.get("workspace_store_key"), "stable-ws-session-99")


if __name__ == "__main__":
    unittest.main()
