"""Strip de thinking e splitter incremental para SSE."""

import unittest

from app.redacted_thinking import (
    RedactedThinkingStreamSplitter,
    assistant_message_for_history,
    split_redacted_thinking_body,
    text_for_agent_tool_json_parse,
)


class TestRedactedThinking(unittest.TestCase):
    def test_split_official_redacted_thinking_tags(self) -> None:
        raw = (
            "<" + "redacted" + "_" + "thinking" + ">chain</" + "redacted" + "_" + "thinking" + ">"
            '{"a":1}'
        )
        rest, inner = split_redacted_thinking_body(raw)
        self.assertEqual(inner, "chain")
        self.assertTrue(rest.strip().startswith("{"))

    def test_split_then_json(self) -> None:
        raw = '<think>passo1</think>\n{"final":"ok","tool_calls":[]}'
        rest, inner = split_redacted_thinking_body(raw)
        self.assertEqual(inner, "passo1")
        self.assertTrue(rest.strip().startswith("{"))

    def test_text_for_parse_strips(self) -> None:
        raw = "<thinking>x</thinking>{\"a\":1}"
        self.assertEqual(text_for_agent_tool_json_parse(raw).strip(), '{"a":1}')

    def test_assistant_history_drops_thinking(self) -> None:
        raw = "<think>long</think>visible"
        self.assertEqual(assistant_message_for_history(raw), "visible")

    def test_stream_splitter_emits_thinking_then_token(self) -> None:
        sp = RedactedThinkingStreamSplitter()
        out: list[tuple[str, dict]] = []
        out.extend(sp.feed("<think>a"))
        out.extend(sp.feed("b</think>"))
        out.extend(sp.feed("hello"))
        kinds = [k for k, _ in out]
        self.assertIn("thinking", kinds)
        self.assertIn("thinking_done", kinds)
        self.assertIn("token", kinds)
        public = "".join(pl["d"] for k, pl in out if k == "token")
        self.assertEqual(public, "hello")

    def test_flush_after_partial_thinking(self) -> None:
        sp = RedactedThinkingStreamSplitter()
        fed = sp.feed("<think>tail")
        self.assertTrue(any(k == "thinking" for k, _ in fed))
        out = sp.flush()
        kinds = [k for k, _ in out]
        self.assertIn("thinking_done", kinds)


if __name__ == "__main__":
    unittest.main()
