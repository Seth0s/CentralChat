"""Fase 10 / G6 — contexto de escrita no canvas (slot activo, grupo no grafo)."""

from __future__ import annotations

from typing import Any

from app.config import CENTRAL_FOCUS_MODE, CENTRAL_MULTISLOT_DEFAULT_SLOT, WIDGET_MULTI_SLOT_ENABLED
from app.shared.multislot_context import effective_active_slot
from app.workspace import load_widget_slot_graph


def connected_component_slots(edges: list[dict[str, Any]], start: int) -> list[int]:
    """Componente conexa em {1..4} contendo ``start`` (arestas não dirigidas)."""
    if not (1 <= int(start) <= 4):
        return []
    adj: dict[int, set[int]] = {i: set() for i in range(1, 5)}
    for e in edges:
        if not isinstance(e, dict):
            continue
        try:
            a = int(e.get("slot_a", 0))
            b = int(e.get("slot_b", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= a <= 4 and 1 <= b <= 4:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[int] = set()
    stack = [int(start)]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(v for v in adj.get(u, ()) if v not in seen)
    return sorted(seen)


def group_id_from_edges(edges: list[dict[str, Any]], slot: int) -> str:
    comp = connected_component_slots(edges, slot)
    if not comp:
        s = max(1, min(4, int(slot)))
        return str(s)
    return "_".join(str(x) for x in comp)


def build_canvas_write_context(
    widget_active_slot: int | None,
    *,
    chat_session_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Contexto passado a ``dispatch_tool`` / workspace canvas.

    - ``enforce_slot_write``: G6 v1 — só o dono do artefacto (``created_by_slot``) igual ao
      slot activo pode ``replace`` / ``apply_canvas_patch``.
    - ``active_slot`` / ``default_slot``: 1–4.
    - ``edges``: snapshot do grafo (para ``group_id`` no TOOL_RESULT).
    """
    default = int(CENTRAL_MULTISLOT_DEFAULT_SLOT)
    active = int(effective_active_slot(widget_active_slot, default))
    enforce = bool(WIDGET_MULTI_SLOT_ENABLED and not CENTRAL_FOCUS_MODE)
    edges: list[dict[str, Any]] = []
    if enforce or WIDGET_MULTI_SLOT_ENABLED:
        try:
            g = load_widget_slot_graph()
            raw = g.get("edges")
            if isinstance(raw, list):
                edges = [x for x in raw if isinstance(x, dict)]
        except Exception:
            edges = []
    out: dict[str, Any] = {
        "enforce_slot_write": enforce,
        "active_slot": active,
        "default_slot": default,
        "edges": edges,
    }
    sid = (chat_session_id or "").strip()
    if len(sid) >= 8:
        out["chat_session_id"] = sid
    if tenant_id and str(tenant_id).strip():
        out["tenant_id"] = str(tenant_id).strip()
    return out
