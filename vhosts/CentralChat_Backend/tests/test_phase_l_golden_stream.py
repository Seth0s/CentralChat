"""L4-1 — fluxo negativo esperado no stream (tool_denied) sem execução real."""
from __future__ import annotations

import contextlib
import unittest
from unittest.mock import MagicMock, patch

import app.tool_loop as tool_loop_mod
from app.tool_loop import iter_agent_tool_stream

from tests.golden_l4_stream_cases import GOLDEN_STREAM_CASES
from tests.stream_ndjson_utils import make_ndjson_side_effect


class TestPhaseLGoldenStreamDeny(unittest.TestCase):
    def _run_stream_case(self, case: dict[str, object]) -> tuple[list[tuple[str, object]], dict]:
        cid = str(case["id"])
        returns = list(case["mock_llm_returns"])  # type: ignore[arg-type]
        mock_llm = MagicMock(side_effect=returns[1:] if len(returns) > 1 else [])
        patch_max = case.get("patch_json_schema_repair_max")

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("app.tool_loop.call_llm", mock_llm))
            stack.enter_context(
                patch(
                    "app.tool_loop.iter_assistant_llm_ndjson",
                    side_effect=make_ndjson_side_effect([returns[0]]),
                )
            )
            if patch_max is not None:
                stack.enter_context(
                    patch.object(
                        tool_loop_mod,
                        "AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS",
                        int(patch_max),
                    )
                )
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text=f"pedido de teste L4 {cid}",
                    base_history=[],
                    request_id=f"l4-golden-{cid}",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        return events, meta

    def test_all_golden_stream_cases(self) -> None:
        for case in GOLDEN_STREAM_CASES:
            cid = str(case["id"])
            with self.subTest(case_id=cid):
                events, meta = self._run_stream_case(case)
                kinds = [e[0] for e in events]
                expect_reason = case.get("expect_tool_denied_reason")
                if expect_reason is not None:
                    self.assertIn("tool_denied", kinds, cid)
                    self.assertIn("token", kinds, cid)
                    denied = next(e[1] for e in events if e[0] == "tool_denied")
                    self.assertEqual(denied.get("reason"), expect_reason, cid)
                    reply = meta.get("reply") or ""
                    self.assertTrue(reply.strip(), cid)
                    if expect_reason == "unknown_or_disallowed_tool":
                        self.assertIn("PROTOCOLO_AGENT_TOOLS", reply, cid)
                else:
                    self.assertNotIn("tool_denied", kinds, cid)
                    self.assertIn("token", kinds, cid)
                    self.assertEqual(meta.get("mode"), "final_direct", cid)

    @patch("app.tool_loop.call_llm")
    def test_unknown_tool_emits_tool_denied(self, mock_llm: MagicMock) -> None:
        streams = [
            '{"final": null, "tool_calls": [{"name": "tool_inventada_l4_golden", "arguments": {}}]}',
        ]
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="pedido de teste L4",
                    base_history=[],
                    request_id="l4-golden-deny",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        kinds = [e[0] for e in events]
        self.assertIn("tool_denied", kinds, "deve negar tool fora do registry")
        self.assertIn("token", kinds, "deve haver resposta textual para o utilizador")
        self.assertIn("PROTOCOLO_AGENT_TOOLS", meta.get("reply", ""))

    def test_stream_with_multi_turn_base_history(self) -> None:
        """F1/A3 — cliente pode enviar histórico; o stream não falha com 2+ turnos no base_history."""
        streams = ['{"final": "Resposta após histórico.", "tool_calls": []}']
        base_history = [
            {"role": "user", "content": "Primeira pergunta."},
            {"role": "assistant", "content": '{"final": "Primeira resposta.", "tool_calls": []}'},
        ]
        with patch(
            "app.tool_loop.iter_assistant_llm_ndjson",
            side_effect=make_ndjson_side_effect(streams),
        ):
            meta: dict = {}
            events = list(
                iter_agent_tool_stream(
                    user_text="Segunda pergunta.",
                    base_history=base_history,
                    request_id="l4-golden-history",
                    profile="balanced",
                    max_tool_executions=1,
                    audit=None,
                    meta_holder=meta,
                    chunk_chars=80,
                )
            )
        kinds = [e[0] for e in events]
        self.assertIn("token", kinds)
        self.assertEqual(meta.get("mode"), "final_direct")
        reply = str(meta.get("reply", ""))
        self.assertIn("após histórico", reply.lower())


if __name__ == "__main__":
    unittest.main()
