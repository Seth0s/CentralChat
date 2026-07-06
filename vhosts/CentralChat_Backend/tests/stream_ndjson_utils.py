"""Helpers para simular `iter_assistant_llm_ndjson` nos testes."""
from __future__ import annotations

import json
from collections.abc import Iterator


def lines_for_raw_response(raw: str) -> list[str]:
    return [
        json.dumps({"e": "token", "d": raw}, ensure_ascii=False) + "\n",
        json.dumps({"e": "done"}, ensure_ascii=False) + "\n",
    ]


def make_ndjson_side_effect(stream_bodies: list[str]):
    """Cada chamada a iter_assistant_llm_ndjson consome o próximo corpo de resposta."""
    idx = [0]

    def _side_effect(*_a, **_k) -> Iterator[str]:
        i = idx[0]
        idx[0] += 1
        if i >= len(stream_bodies):
            raise RuntimeError(f"iter_assistant_llm_ndjson: chamada extra (indice {i})")
        return iter(lines_for_raw_response(stream_bodies[i]))

    return _side_effect
