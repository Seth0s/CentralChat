"""Fase 9 — contexto multi-slot a partir do grafo (G3). Ver docs/UI_BACKEND_CONTRACT.md §10.1."""

from __future__ import annotations

import json
import re
from typing import Any

_SLOT_PREFIX_RE = re.compile(r"^slot:([1-4]):\s*", re.IGNORECASE)


def effective_active_slot(request_slot: int | None, default_slot: int) -> int:
    if request_slot is not None and 1 <= int(request_slot) <= 4:
        return int(request_slot)
    d = int(default_slot)
    return max(1, min(4, d))


def graph_neighbors(edges: list[dict[str, Any]], active: int, max_edges: int) -> list[int]:
    """Slots ligados ao `active` por arestas, ordenados 1→4; no máximo `max_edges` vizinhos."""
    nbr: set[int] = set()
    for e in edges:
        if not isinstance(e, dict):
            continue
        try:
            a = int(e.get("slot_a", 0))
            b = int(e.get("slot_b", 0))
        except (TypeError, ValueError):
            continue
        if a == active:
            nbr.add(b)
        elif b == active:
            nbr.add(a)
    ordered = sorted(x for x in nbr if 1 <= x <= 4)
    lim = max(0, int(max_edges))
    return ordered[:lim] if lim else []


def partition_messages_by_slot(
    messages: list[dict[str, str]], default_slot: int
) -> dict[int, list[dict[str, str]]]:
    """Reparte mensagens por prefixo `slot:N:` no início do conteúdo; sem prefixo → `default_slot`."""
    buckets: dict[int, list[dict[str, str]]] = {1: [], 2: [], 3: [], 4: []}
    for m in messages:
        role = str(m.get("role", "") or "").strip()
        content = str(m.get("content", "") or "")
        slot = default_slot
        mo = _SLOT_PREFIX_RE.match(content)
        if mo:
            slot = int(mo.group(1))
            content = content[mo.end() :].lstrip()
        if 1 <= slot <= 4:
            buckets[slot].append({"role": role, "content": content})
        else:
            buckets[default_slot].append({"role": role, "content": content})
    return buckets


def first_turn_from_history(messages: list[dict[str, str]]) -> bool:
    """Sem mensagem `assistant` → primeiro turno (§10.1)."""
    return not any(str(m.get("role", "")).strip() == "assistant" for m in messages)


def build_multislot_system_message(
    *,
    active: int,
    neighbor_slots: list[int],
    graph_version: int,
) -> dict[str, str]:
    payload = {
        "schema_version": 1,
        "active_slot": active,
        "neighbor_slots": list(neighbor_slots),
        "widget_slot_graph_version": int(graph_version),
    }
    body = (
        "[MULTISLOT] Contexto de slots do widget (JSON; não substitui o grafo persistido). "
        + json.dumps(payload, ensure_ascii=False)
    )
    return {"role": "system", "content": body}


def _total_chars(rows: list[dict[str, str]]) -> int:
    return sum(len(str(m.get("content", "") or "")) for m in rows)


def apply_multislot_to_compacted_history(
    *,
    compacted_history: list[dict[str, str]],
    active_slot: int,
    neighbor_slots: list[int],
    neighbor_max_messages: int,
    aggregate_max_chars: int,
    first_turn: bool,
    first_turn_include_neighbors: bool,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    Reordena: mensagens do slot activo (cronológicas), depois até M mensagens por vizinho
    (últimas por slot), com prefixo `slot:N:`. Mensagens de slots não ligados ao activo
    pelo grafo são omitidas (lista em meta).
    """
    buckets = partition_messages_by_slot(compacted_history, active_slot)
    allowed = {active_slot, *neighbor_slots}
    omitted_non_neighbor: list[int] = []
    for s in (1, 2, 3, 4):
        if s not in allowed and buckets[s]:
            omitted_non_neighbor.append(s)

    active_msgs = list(buckets[active_slot])
    skip_neighbors = bool(first_turn and not first_turn_include_neighbors)
    neighbor_blocks: list[dict[str, str]] = []
    if not skip_neighbors:
        mlim = max(0, int(neighbor_max_messages))
        for ns in neighbor_slots:
            if ns == active_slot:
                continue
            raw = list(buckets[ns])
            chunk = raw[-mlim:] if mlim else []
            for m in chunk:
                c = str(m.get("content", "") or "")
                prefix = f"slot:{ns}: "
                if not re.match(rf"^slot:{ns}:\s*", c, re.IGNORECASE):
                    c = prefix + c
                neighbor_blocks.append({"role": m["role"], "content": c})

    truncated = False
    active_work = list(active_msgs)
    neighbor_work = list(neighbor_blocks)
    ac = _total_chars(active_work)
    nc = _total_chars(neighbor_work)
    budget = max(1, int(aggregate_max_chars))

    while neighbor_work and ac + nc > budget:
        neighbor_work.pop(0)
        truncated = True
        nc = _total_chars(neighbor_work)
    while active_work and ac + nc > budget:
        active_work.pop(0)
        truncated = True
        ac = _total_chars(active_work)

    new_hist = active_work + neighbor_work
    injected: set[int] = set()
    if active_work:
        injected.add(active_slot)
    for m in neighbor_work:
        mo = _SLOT_PREFIX_RE.match(str(m.get("content", "") or ""))
        if mo:
            injected.add(int(mo.group(1)))

    meta: dict[str, Any] = {
        "schema_version": 1,
        "active_slot": active_slot,
        "injected_slots": sorted(injected),
        "truncated": truncated,
        "aggregate_chars": _total_chars(new_hist),
        "first_turn_neighbors_skipped": skip_neighbors,
    }
    if omitted_non_neighbor:
        meta["omitted_non_neighbor_slots"] = sorted(set(omitted_non_neighbor))
    return new_hist, meta
