import unittest

from app.tool_loop import (
    extract_json_object,
    parse_agent_tool_response,
    TOOL_NAME_P0,
)


class TestToolLoop(unittest.TestCase):
    def test_parse_direct_json(self):
        raw = '{"final": "ok", "tool_calls": []}'
        f, calls, ok = parse_agent_tool_response(raw)
        self.assertTrue(ok)
        self.assertEqual(f, "ok")
        self.assertEqual(calls, [])

    def test_parse_fenced_json(self):
        raw = '```json\n{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}\n```' % TOOL_NAME_P0
        f, calls, ok = parse_agent_tool_response(raw)
        self.assertTrue(ok)
        self.assertIsNone(f)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("name"), TOOL_NAME_P0)

    def test_parse_non_json_fallback(self):
        f, calls, ok = parse_agent_tool_response("isto nao e json")
        self.assertFalse(ok)
        self.assertEqual(calls, [])

    def test_extract_embedded(self):
        raw = 'preamble {"final": "x", "tool_calls": []} tail'
        d = extract_json_object(raw)
        self.assertIsNotNone(d)
        self.assertEqual(d.get("final"), "x")


if __name__ == "__main__":
    unittest.main()
