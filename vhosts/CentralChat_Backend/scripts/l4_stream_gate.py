#!/usr/bin/env python3
"""
L4-2 — gate de regressão para stream agent-tools (sem LLM real; mock de call_llm).

Corre a mesma tabela que `tests/golden_l4_stream_cases.py` e termina com código ≠0
se algum caso falhar (limiar 100%% para esta bateria).

Uso (directório orchestrator):
  PYTHONPATH=. python scripts/l4_stream_gate.py
  PYTHONPATH=. python scripts/l4_stream_gate.py --json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ORCH = Path(__file__).resolve().parents[1]
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import app.tool_loop as tool_loop_mod  # noqa: E402
from app.tool_loop import iter_agent_tool_stream  # noqa: E402
from tests.golden_l4_stream_cases import GOLDEN_STREAM_CASES  # noqa: E402
from tests.stream_ndjson_utils import make_ndjson_side_effect  # noqa: E402


def _run_one(case: dict[str, object]) -> str | None:
    cid = str(case["id"])
    returns = list(case["mock_llm_returns"])  # type: ignore[arg-type]
    expect_reason = case.get("expect_tool_denied_reason")
    patch_max = case.get("patch_json_schema_repair_max")

    mock_llm = MagicMock(side_effect=returns[1:] if len(returns) > 1 else [])

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
                user_text=f"golden stream gate {cid}",
                base_history=[],
                request_id=f"l4-stream-gate-{cid}",
                profile="balanced",
                max_tool_executions=1,
                audit=None,
                meta_holder=meta,
                chunk_chars=80,
            )
        )
    kinds = [e[0] for e in events]

    if expect_reason is not None:
        if "tool_denied" not in kinds:
            return f"{cid}: expected tool_denied in events, got {kinds!r}"
        denied = next((e[1] for e in events if e[0] == "tool_denied"), {})
        got = denied.get("reason")
        if got != expect_reason:
            return f"{cid}: expect_tool_denied_reason={expect_reason!r} got {got!r}"
        reply = meta.get("reply") or ""
        if not reply.strip():
            return f"{cid}: empty reply after tool_denied"
        if expect_reason == "unknown_or_disallowed_tool" and "PROTOCOLO_AGENT_TOOLS" not in reply:
            return f"{cid}: reply missing PROTOCOLO_AGENT_TOOLS marker"
        return None

    if "tool_denied" in kinds:
        return f"{cid}: unexpected tool_denied in {kinds!r}"
    if "token" not in kinds:
        return f"{cid}: expected token events, got {kinds!r}"
    if meta.get("mode") != "final_direct":
        return f"{cid}: expect mode final_direct got {meta.get('mode')!r}"
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="L4 golden stream gate")
    p.add_argument("--json", action="store_true", help="Emitir uma linha JSON com métricas")
    args = p.parse_args()

    failures: list[str] = []
    for case in GOLDEN_STREAM_CASES:
        err = _run_one(case)
        if err:
            failures.append(err)

    total = len(GOLDEN_STREAM_CASES)
    passed = total - len(failures)
    rate = passed / total if total else 1.0
    payload = {
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "rate": round(rate, 6),
        "failures": failures,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(
            f"L4 stream gate: {passed}/{total} passed (rate={rate:.4f})",
            file=sys.stderr,
        )
        for line in failures:
            print(line, file=sys.stderr)

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
