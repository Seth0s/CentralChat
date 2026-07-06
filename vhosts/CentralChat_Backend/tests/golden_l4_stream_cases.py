"""
L4-1 — casos canónicos de stream agent-tools (sem LLM real; mock de call_llm).

Fonte única para `test_phase_l_golden_stream` e `scripts/l4_stream_gate.py`.
"""
from __future__ import annotations

from app.tool_registry import TOOL_NAME_LIST_PROCESSES

# mock_llm_returns: sequência devolvida por call_llm (cada chamada consome o próximo item).
# expect_tool_denied_reason: quando se espera tool_denied antes do fim (None = não exigir deny).
GOLDEN_STREAM_CASES: list[dict[str, object]] = [
    {
        "id": "deny_unknown_tool",
        "mock_llm_returns": [
            '{"final": null, "tool_calls": [{"name": "tool_inventada_l4_stream", "arguments": {}}]}'
        ],
        "expect_tool_denied_reason": "unknown_or_disallowed_tool",
        "patch_json_schema_repair_max": None,
    },
    {
        "id": "deny_invalid_arguments_list_processes",
        "mock_llm_returns": [
            (
                '{"final": null, "tool_calls": [{"name": "%s", "arguments": {"limit": "not_an_integer"}}]}'
                % TOOL_NAME_LIST_PROCESSES
            )
        ],
        "expect_tool_denied_reason": "invalid_arguments",
        "patch_json_schema_repair_max": 0,
    },
    {
        "id": "final_direct_no_tools",
        "mock_llm_returns": ['{"final": "Resposta directa L4.", "tool_calls": []}'],
        "expect_tool_denied_reason": None,
    },
]
