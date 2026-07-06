"""
I+ — POST /assistant/text/stream via ASGI (TestClient), com agent tools mockados.

Carga leve: vários pedidos sequenciais com o mesmo mock (sem rede LLM real).
Prioridade #2: cobrir tool_result, invalid_arguments, erro HTTP no dispatch, stream sem tools, texto não-JSON, reparo JSON.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import httpx

from tests.stream_ndjson_utils import make_ndjson_side_effect

app = None
TestClient = None
try:
    from fastapi.testclient import TestClient as _TestClient

    from app.server import app as _app

    TestClient = _TestClient
    app = _app
except ImportError:  # pragma: no cover
    pass


def _ndjson_repeat(body: str):
    """Cada chamada devolve um iterador NDJSON com um único token + done."""

    def _one(*_a, **_k):
        return iter(
            [
                json.dumps({"e": "token", "d": body}, ensure_ascii=False) + "\n",
                json.dumps({"e": "done"}, ensure_ascii=False) + "\n",
            ]
        )

    return _one


@unittest.skipUnless(app is not None and TestClient is not None, "FastAPI app em falta")
class TestAssistantTextStreamIPlus(unittest.TestCase):
    _payload_tools: dict = {
        "text": "pergunta de teste I+ stream",
        "history": [],
        "use_agent_tools": True,
        "include_host_context": False,
        "include_memory_recall": False,
        "include_long_session_memory": False,
        "include_playbook": False,
    }

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.iter_assistant_llm_ndjson")
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_agent_tools_tool_denied_in_sse(
        self,
        mock_llm: MagicMock,
        mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        streams = [
            '{"final": null, "tool_calls": [{"name": "tool_inventada_http_i_plus", "arguments": {}}]}',
        ]
        mock_ndjson.side_effect = make_ndjson_side_effect(streams)
        client = TestClient(app)
        with client.stream(
            "POST",
            "/assistant/text/stream",
            json=self._payload_tools,
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: start", body)
        self.assertIn('"ui_trace"', body)
        self.assertIn("injection_summary_pt", body)
        self.assertIn("event: tool_denied", body)
        self.assertIn("event: token", body)
        self.assertIn("event: done", body)
        self.assertIn("unknown_or_disallowed_tool", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.iter_assistant_llm_ndjson")
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_many_requests_smoke(
        self,
        mock_llm: MagicMock,
        mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        """Smoke de carga: repetir o mesmo pedido stream N vezes (mock rápido)."""
        mock_ndjson.side_effect = _ndjson_repeat(
            '{"final": "Resposta curta.", "tool_calls": []}',
        )
        client = TestClient(app)
        for i in range(24):
            with self.subTest(i=i):
                with client.stream(
                    "POST",
                    "/assistant/text/stream",
                    json=self._payload_tools,
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    body = resp.read().decode("utf-8")
                self.assertIn("event: done", body, body[:500])
                self.assertIn("Resposta curta", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.dispatch_tool")
    @patch("app.tool_loop.iter_assistant_llm_ndjson")
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_tool_result_get_host_summary(
        self,
        mock_llm: MagicMock,
        mock_ndjson: MagicMock,
        mock_dispatch: MagicMock,
        _audit: MagicMock,
    ) -> None:
        mock_dispatch.return_value = {"request_id": "rid-tool", "system_agent": {"ok": True}}
        streams = [
            '{"final": null, "tool_calls": [{"name": "get_host_summary", "arguments": {}}]}',
            '{"final": "Resumo apos tool.", "tool_calls": []}',
        ]
        mock_ndjson.side_effect = make_ndjson_side_effect(streams)
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload_tools) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: tool_proposed", body)
        self.assertIn('"tool": "get_host_summary"', body)
        self.assertIn("event: tool_result", body)
        self.assertIn('"ok": true', body)
        self.assertIn("event: done", body)
        mock_dispatch.assert_called_once()
        self.assertEqual(mock_llm.call_count, 0)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.iter_assistant_llm_ndjson", side_effect=make_ndjson_side_effect([]))
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_tool_denied_invalid_arguments(
        self,
        mock_llm: MagicMock,
        mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        streams = [
            '{"final": null, "tool_calls": [{"name": "list_processes", "arguments": {"limit": 0}}]}',
        ]
        mock_ndjson.side_effect = make_ndjson_side_effect(streams)
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload_tools) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: tool_denied", body)
        self.assertIn("invalid_arguments", body)
        self.assertIn("event: done", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.dispatch_tool", side_effect=httpx.HTTPError("system-agent down"))
    @patch("app.tool_loop.iter_assistant_llm_ndjson", side_effect=make_ndjson_side_effect([]))
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_dispatch_http_error_emits_sse_error(
        self,
        mock_llm: MagicMock,
        mock_ndjson: MagicMock,
        _dispatch: MagicMock,
        _audit: MagicMock,
    ) -> None:
        streams = ['{"final": null, "tool_calls": [{"name": "get_host_summary", "arguments": {}}]}']
        mock_ndjson.side_effect = make_ndjson_side_effect(streams)
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload_tools) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: tool_proposed", body)
        self.assertIn("event: error", body)
        self.assertIn("system-agent down", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_without_agent_tools_uses_ndjson_path(
        self,
        mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        def _lines() -> object:
            yield json.dumps({"e": "token", "d": "Olá "}, ensure_ascii=False)
            yield json.dumps({"e": "token", "d": "mundo."}, ensure_ascii=False)
            yield json.dumps({"e": "done"}, ensure_ascii=False)

        mock_ndjson.return_value = _lines()
        client = TestClient(app)
        payload = {**self._payload_tools, "use_agent_tools": False}
        with client.stream("POST", "/assistant/text/stream", json=payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        mock_ndjson.assert_called_once()
        self.assertIn("event: token", body)
        self.assertIn("Olá ", body)
        self.assertIn("event: done", body)
        self.assertNotIn("tool_proposed", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.server.iter_ndjson_lines_with_stream_fallback")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_ndjson_error_event(self, mock_ndjson: MagicMock, _audit: MagicMock) -> None:
        mock_ndjson.return_value = iter([json.dumps({"e": "error", "message": "falha upstream"})])
        client = TestClient(app)
        payload = {**self._payload_tools, "use_agent_tools": False}
        with client.stream("POST", "/assistant/text/stream", json=payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("event: error", body)
        self.assertIn("falha upstream", body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 1)
    @patch("app.tool_loop.iter_assistant_llm_ndjson", side_effect=make_ndjson_side_effect(["isto nao e json"]))
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_json_repair_then_final_without_tools(
        self,
        mock_llm: MagicMock,
        _mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        """Primeira resposta inválida → uma chamada extra de reparo → envelope válido só com final."""
        mock_llm.side_effect = [
            '{"final": "Corrigido.", "tool_calls": []}',
        ]
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload_tools) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertGreaterEqual(mock_llm.call_count, 1)
        self.assertIn("Corrigido.", body)
        self.assertIn("event: done", body)
        self.assertIn('"json_repair_extra_calls": 1', body)

    @patch("app.server.write_orchestrator_audit")
    @patch("app.tool_loop.AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch("app.tool_loop.AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", 0)
    @patch(
        "app.tool_loop.iter_assistant_llm_ndjson",
        side_effect=make_ndjson_side_effect(["Resposta em prosa sem envelope JSON."]),
    )
    @patch("app.tool_loop.call_llm")
    @patch("app.server.AGENT_TOOLS_ENABLED", True)
    def test_stream_non_json_llm_emits_tokens_plain_text_mode(
        self,
        mock_llm: MagicMock,
        _mock_ndjson: MagicMock,
        _audit: MagicMock,
    ) -> None:
        client = TestClient(app)
        with client.stream("POST", "/assistant/text/stream", json=self._payload_tools) as resp:
            self.assertEqual(resp.status_code, 200)
            body = resp.read().decode("utf-8")
        self.assertNotIn("event: tool_proposed", body)
        self.assertIn("event: token", body)
        self.assertIn("prosa", body)
        self.assertIn("event: done", body)


if __name__ == "__main__":
    unittest.main()
