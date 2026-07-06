#!/usr/bin/env python3
"""
L4-2 — gate de regressão para parse golden (sem LLM).

Corre a mesma tabela que `tests/golden_l4_parse_cases.py` e termina com código ≠0
se algum caso falhar (limiar 100%% para esta bateria).

Uso (directório orchestrator):
  PYTHONPATH=. python scripts/l4_golden_gate.py
  PYTHONPATH=. python scripts/l4_golden_gate.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Garantir import do pacote `app` e dos testes
_ORCH = Path(__file__).resolve().parents[1]
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from app.tool_loop import parse_agent_tool_response  # noqa: E402
from tests.golden_l4_parse_cases import GOLDEN_PARSE_CASES  # noqa: E402


def _check_one(case: dict[str, object]) -> str | None:
    cid = str(case["id"])
    raw = str(case["raw"])
    expect_ok = bool(case["expect_ok"])
    f, calls, ok = parse_agent_tool_response(raw)
    if ok != expect_ok:
        return f"{cid}: expect_ok={expect_ok} got ok={ok}"
    if not expect_ok:
        return None
    if "expect_final" in case:
        if f != case["expect_final"]:
            return f"{cid}: expect_final={case['expect_final']!r} got {f!r}"
    if "expect_tool_names" in case:
        names = [str(c.get("name", "")) for c in calls]
        exp = list(case["expect_tool_names"])  # type: ignore[arg-type]
        if names != exp:
            return f"{cid}: expect_tool_names={exp!r} got {names!r}"
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="L4 golden parse gate")
    p.add_argument("--json", action="store_true", help="Emitir uma linha JSON com métricas")
    args = p.parse_args()

    failures: list[str] = []
    for case in GOLDEN_PARSE_CASES:
        err = _check_one(case)
        if err:
            failures.append(err)

    total = len(GOLDEN_PARSE_CASES)
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
            f"L4 golden gate: {passed}/{total} passed (rate={rate:.4f})",
            file=sys.stderr,
        )
        for line in failures:
            print(line, file=sys.stderr)

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
