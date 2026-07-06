"""
L4-1 — casos canónicos de parse do envelope agent-tools (sem LLM).

Fonte única para `test_phase_l_golden_parse` e `scripts/l4_golden_gate.py`.
"""
from __future__ import annotations

from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_LIST_PROCESSES

# Cada entrada: id, raw, expect_ok, e opcionalmente expect_final e/ou expect_tool_names (ordem).
GOLDEN_PARSE_CASES: list[dict[str, object]] = [
    {
        "id": "valid_minimal_final_only",
        "raw": '{"final": "Resposta.", "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "Resposta.",
        "expect_tool_names": [],
    },
    {
        "id": "redacted_thinking_then_json",
        "raw": (
            "<" + "redacted" + "_" + "thinking" + ">passo interno</" + "redacted" + "_" + "thinking" + ">"
            + '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_GET_HOST_SUMMARY],
    },
    {
        "id": "plain_thinking_tags_then_json",
        "raw": (
            "<thinking>outro formato</thinking>"
            '{"final": "ok", "tool_calls": []}'
        ),
        "expect_ok": True,
        "expect_final": "ok",
        "expect_tool_names": [],
    },
    {
        "id": "valid_tool_call_host_summary",
        "raw": (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_GET_HOST_SUMMARY],
    },
    {
        "id": "valid_two_tools",
        "raw": (
            '{"final": null, "tool_calls": ['
            '{"name": "%s", "arguments": {}},'
            '{"name": "%s", "arguments": {"limit": 5}}'
            "]}"
            % (TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_LIST_PROCESSES)
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_LIST_PROCESSES],
    },
    {
        "id": "final_null_explicit",
        "raw": '{"final": null, "tool_calls": []}',
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [],
    },
    {
        "id": "final_empty_string_becomes_none",
        "raw": '{"final": "", "tool_calls": []}',
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [],
    },
    {
        "id": "final_numeric_coerced_to_string",
        "raw": '{"final": 42, "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "42",
        "expect_tool_names": [],
    },
    {
        "id": "unicode_final",
        "raw": '{"final": "Café ☀️", "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "Café ☀️",
        "expect_tool_names": [],
    },
    {
        "id": "missing_tool_calls_defaults_empty_list",
        "raw": '{"final": "so final"}',
        "expect_ok": True,
        "expect_final": "so final",
        "expect_tool_names": [],
    },
    {
        "id": "extra_top_level_keys_ignored",
        "raw": '{"final": "ok", "tool_calls": [], "meta": {"x": 1}}',
        "expect_ok": True,
        "expect_final": "ok",
        "expect_tool_names": [],
    },
    {
        "id": "embedded_json_in_prose",
        "raw": 'Prefixo texto {"final": "fim", "tool_calls": []} sufixo.',
        "expect_ok": True,
        "expect_final": "fim",
        "expect_tool_names": [],
    },
    {
        "id": "markdown_code_fence_json",
        "raw": '```json\n{"final": "dentro", "tool_calls": []}\n```',
        "expect_ok": True,
        "expect_final": "dentro",
        "expect_tool_names": [],
    },
    {
        "id": "markdown_code_fence_plain",
        "raw": '```\n{"final": "plain", "tool_calls": []}\n```',
        "expect_ok": True,
        "expect_final": "plain",
        "expect_tool_names": [],
    },
    {
        "id": "whitespace_padded_object",
        "raw": '\n\n  {"final": "pad", "tool_calls": []}  \n',
        "expect_ok": True,
        "expect_final": "pad",
        "expect_tool_names": [],
    },
    {
        "id": "tool_calls_filters_non_dict",
        "raw": (
            '{"final": null, "tool_calls": ["bad", {"name": "%s", "arguments": {}}]}'
            % TOOL_NAME_GET_HOST_SUMMARY
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_GET_HOST_SUMMARY],
    },
    {
        "id": "tool_calls_dict_not_list_becomes_empty",
        "raw": '{"final": "x", "tool_calls": {"name": "nope", "arguments": {}}}',
        "expect_ok": True,
        "expect_final": "x",
        "expect_tool_names": [],
    },
    {
        "id": "reject_top_level_array",
        "raw": '[{"final": "x", "tool_calls": []}]',
        "expect_ok": False,
    },
    {
        "id": "reject_invalid_json",
        "raw": "not json at all {{{",
        "expect_ok": False,
    },
    {
        "id": "reject_unclosed_brace",
        "raw": '{"final": "incomplete"',
        "expect_ok": False,
    },
    {
        "id": "reject_primitive_string",
        "raw": '"just a string"',
        "expect_ok": False,
    },
    {
        "id": "reject_primitive_true",
        "raw": "true",
        "expect_ok": False,
    },
    {
        "id": "reject_empty_after_strip",
        "raw": "   ",
        "expect_ok": False,
    },
    {
        "id": "utf8_bom_prefix_valid_object",
        "raw": '\ufeff{"final": "apos_bom", "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "apos_bom",
        "expect_tool_names": [],
    },
    {
        "id": "final_false_bool_coerced_to_string",
        "raw": '{"final": false, "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "False",
        "expect_tool_names": [],
    },
    {
        "id": "final_true_bool_coerced_to_string",
        "raw": '{"final": true, "tool_calls": []}',
        "expect_ok": True,
        "expect_final": "True",
        "expect_tool_names": [],
    },
    {
        "id": "reject_adjacent_json_objects",
        "raw": '{"final": "a", "tool_calls": []}{"final": "b", "tool_calls": []}',
        "expect_ok": False,
    },
    {
        "id": "valid_list_processes_with_limit",
        "raw": (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": {"limit": 7}}]}'
            % TOOL_NAME_LIST_PROCESSES
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_LIST_PROCESSES],
    },
    {
        "id": "tool_call_missing_name_defaults_empty",
        "raw": '{"final": null, "tool_calls": [{"arguments": {}}]}',
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [""],
    },
    {
        "id": "tool_arguments_null_still_parses",
        "raw": (
            '{"final": null, "tool_calls": [{"name": "%s", "arguments": null}]}' % TOOL_NAME_GET_HOST_SUMMARY
        ),
        "expect_ok": True,
        "expect_final": None,
        "expect_tool_names": [TOOL_NAME_GET_HOST_SUMMARY],
    },
    {
        "id": "deeply_nested_braces_in_final_string",
        "raw": r'{"final": "{\"k\":1}", "tool_calls": []}',
        "expect_ok": True,
        "expect_final": '{"k":1}',
        "expect_tool_names": [],
    },
]
