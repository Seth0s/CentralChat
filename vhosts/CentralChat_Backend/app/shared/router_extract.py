"""Extracto / orçamento de histórico enviado ao model-router (pré-Fase 7)."""

from __future__ import annotations

from typing import Any


def _count_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(str(m.get("content", "") or "")) for m in messages)


def slim_injected_history_for_router(
    prefix_messages: list[dict[str, str]],
    compacted_history: list[dict[str, str]],
    *,
    max_messages: int,
    max_chars: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    Preserva todos os prefixos (system / digest / RAG); limita só a cauda conversacional.

    Devolve ``(histórico_completo, auditoria)`` com contagens antes/depois.
    """
    tail = list(compacted_history)
    audit: dict[str, Any] = {
        "prefix_len": len(prefix_messages),
        "tail_messages_before": len(tail),
        "chars_prefix_before": _count_chars(prefix_messages),
        "chars_tail_before": _count_chars(tail),
        "max_messages": max_messages,
        "max_chars": max_chars,
    }
    if max_messages > 0 and len(tail) > max_messages:
        tail = tail[-max_messages:]
    merged = [*prefix_messages, *tail]
    total_chars = _count_chars(merged)
    if max_chars > 0 and total_chars > max_chars:
        while tail and _count_chars([*prefix_messages, *tail]) > max_chars:
            tail.pop(0)
        merged = [*prefix_messages, *tail]
    audit["tail_messages_after"] = len(tail)
    audit["chars_tail_after"] = _count_chars(tail)
    audit["chars_total_after"] = _count_chars(merged)
    audit["tail_dropped"] = max(0, audit["tail_messages_before"] - audit["tail_messages_after"])
    return merged, audit
