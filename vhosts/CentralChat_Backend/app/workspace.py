"""Workspace domain — widget slot graph, canvas, multi-artifact management, PG store.

Consolidated from:
  - widget_slot_graph.py       (SSOT slot graph 1–4)
  - workspace_store_pg.py      (Postgres persistence)
  - workspace_canvas.py        (canvas patches, manage_workspace_artifact, metrics)
  - workspace.py               (API router)
  - repositories/widget_slot_repository.py (re-export shim)
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from prometheus_client import Gauge
from pydantic import BaseModel, Field

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore

from app.config import (
    WIDGET_MULTI_SLOT_ENABLED,
    WIDGET_SLOT_GRAPH_STORE_PATH,
    WORKSPACE_PG_URL,
    WORKSPACE_SESSION_TTL_SECONDS,
    WORKSPACE_STORE_BACKEND,
)

# ═══════════════════════════════════════════════════════════════════
# SLOT GRAPH (SSOT 1–4, simétrico v1)
# ═══════════════════════════════════════════════════════════════════

SLOT_MIN = 1
SLOT_MAX = 4


def _slot_graph_store_path() -> Path:
    from app.shared.tenant_paths import resolve_widget_slot_graph_path

    return resolve_widget_slot_graph_path(WIDGET_SLOT_GRAPH_STORE_PATH or "")


def default_graph_state() -> dict[str, Any]:
    return {"version": 0, "edges": []}


def _normalize_edge(a: int, b: int) -> tuple[int, int] | None:
    if a == b:
        return None
    if not (SLOT_MIN <= a <= SLOT_MAX and SLOT_MIN <= b <= SLOT_MAX):
        return None
    return (a, b) if a < b else (b, a)


def normalize_edges(raw: list[dict[str, Any]] | list[list[int]]) -> list[dict[str, int]]:
    seen: set[tuple[int, int]] = set()
    out: list[dict[str, int]] = []
    for item in raw:
        a: int | None = None
        b: int | None = None
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                a = int(item[0])
                b = int(item[1])
            except (TypeError, ValueError):
                continue
        elif isinstance(item, dict):
            try:
                a = int(item.get("slot_a") or item.get("a") or 0)
                b = int(item.get("slot_b") or item.get("b") or 0)
            except (TypeError, ValueError):
                continue
        if a is None or b is None:
            continue
        pair = _normalize_edge(a, b)
        if not pair or pair in seen:
            continue
        seen.add(pair)
        out.append({"slot_a": pair[0], "slot_b": pair[1]})
    out.sort(key=lambda e: (e["slot_a"], e["slot_b"]))
    return out


def load_widget_slot_graph() -> dict[str, Any]:
    base = default_graph_state()
    path = _slot_graph_store_path()
    if not path.is_file():
        return dict(base)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(base)
    if not isinstance(raw, dict):
        return dict(base)
    ver = raw.get("version")
    try:
        version = int(ver) if ver is not None else 0
    except (TypeError, ValueError):
        version = 0
    edges_raw = raw.get("edges")
    edges: list[dict[str, int]] = []
    if isinstance(edges_raw, list):
        edges = normalize_edges(edges_raw)
    return {"version": max(0, version), "edges": edges}


def replace_widget_slot_graph(*, expected_version: int, edges: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Escreve novo grafo se `expected_version` coincidir com o persistido.
    Devolve o novo estado ou None em caso de conflito.
    """
    current = load_widget_slot_graph()
    if int(current.get("version") or 0) != int(expected_version):
        return None
    norm = normalize_edges(edges)
    new_version = int(current.get("version") or 0) + 1
    data = {"version": new_version, "edges": norm}
    path = _slot_graph_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def apply_preset(preset: str) -> list[dict[str, int]]:
    p = (preset or "").strip().lower()
    if p in ("isolated", "none"):
        return []
    if p in ("full", "complete"):
        pairs: list[tuple[int, int]] = []
        for a in range(SLOT_MIN, SLOT_MAX + 1):
            for b in range(a + 1, SLOT_MAX + 1):
                pairs.append((a, b))
        return [{"slot_a": x, "slot_b": y} for x, y in pairs]
    if p in ("example_1_4", "1_4"):
        return [{"slot_a": 1, "slot_b": 4}]
    return []


# ═══════════════════════════════════════════════════════════════════
# STORE PG (F2/A2 — Postgres JSONB + TTL)
# ═══════════════════════════════════════════════════════════════════

_schema_lock = threading.Lock()
_schema_ready = False


def _ws_pg_connect():
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(WORKSPACE_PG_URL, autocommit=True)


def ensure_workspace_table() -> None:
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        with _ws_pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_sessions (
                      store_key TEXT PRIMARY KEY,
                      payload JSONB NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      expires_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workspace_sessions_expires_at
                    ON workspace_sessions (expires_at);
                    """
                )
        _schema_ready = True


def _ws_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=max(60, WORKSPACE_SESSION_TTL_SECONDS))


def load_bucket(store_key: str) -> dict[str, Any] | None:
    """Devolve ``{"artifacts": {...}}`` ou ``None`` se não existir ou estiver expirado."""
    ensure_workspace_table()
    with _ws_pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM workspace_sessions
                WHERE store_key = %s AND expires_at <= NOW();
                """,
                (store_key,),
            )
            cur.execute(
                """
                SELECT payload FROM workspace_sessions
                WHERE store_key = %s AND expires_at > NOW();
                """,
                (store_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row[0]
            if isinstance(payload, dict):
                arts = payload.get("artifacts")
                if isinstance(arts, dict):
                    return {"artifacts": arts}
            return {"artifacts": {}}


def save_bucket(store_key: str, bucket: dict[str, Any]) -> None:
    """Persiste o bucket completo e renova o TTL. Bucket sem artefactos remove a linha (evita lixo pós-erro)."""
    ensure_workspace_table()
    artifacts = bucket.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    if len(artifacts) == 0:
        with _ws_pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM workspace_sessions WHERE store_key = %s;", (store_key,))
        return
    payload = {"artifacts": artifacts}
    exp = _ws_expires_at()
    payload_json = json.dumps(payload, ensure_ascii=False)
    with _ws_pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO workspace_sessions (store_key, payload, expires_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (store_key) DO UPDATE SET
                  payload = EXCLUDED.payload,
                  expires_at = EXCLUDED.expires_at,
                  updated_at = NOW();
                """,
                (store_key, payload_json, exp),
            )


def delete_expired_sessions() -> int:
    """Remove linhas expiradas; retorna número de apagadas."""
    ensure_workspace_table()
    with _ws_pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workspace_sessions WHERE expires_at <= NOW();")
            return int(cur.rowcount or 0)


def count_and_payload_bytes() -> tuple[int, int]:
    """Para métricas: (nº de sessões activas, soma aproximada dos bytes do JSON)."""
    ensure_workspace_table()
    with _ws_pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::bigint,
                       COALESCE(SUM(octet_length(payload::text)), 0)::bigint
                FROM workspace_sessions
                WHERE expires_at > NOW();
                """
            )
            row = cur.fetchone()
            if not row:
                return 0, 0
            return int(row[0] or 0), int(row[1] or 0)


# ═══════════════════════════════════════════════════════════════════
# CANVAS (T2 — multi-artifact, canvas patches, metrics)
# ═══════════════════════════════════════════════════════════════════

_MAX_CONTENT_CHARS = 400_000
_MAX_TITLE_LEN = 200

_lock = threading.Lock()
# Chave = workspace store key (session estável ou request_id por pedido). Só para backend memory.
_by_request: dict[str, dict[str, Any]] = {}

WORKSPACE_SESSIONS = Gauge(
    "central_orchestrator_workspace_sessions",
    "Número de sessões de workspace activas (não expiradas no postgres; chaves no dict em memory)",
)
WORKSPACE_PAYLOAD_BYTES = Gauge(
    "central_orchestrator_workspace_store_payload_bytes",
    "Tamanho aproximado (bytes) dos payloads do workspace",
)

_metrics_last_monotonic = 0.0
_METRICS_MIN_INTERVAL = 30.0


def _use_postgres() -> bool:
    return WORKSPACE_STORE_BACKEND == "postgres"


@contextmanager
def _bucket_transaction(store_key: str) -> Generator[dict[str, Any], None, None]:
    """
    Garante um dict mutável com chave ``artifacts`` (mapa artifact_id -> slot).
    Em postgres, carrega antes e grava depois; em memory, mantém referência partilhada.
    """
    with _lock:
        if _use_postgres():
            bucket = load_bucket(store_key)
            if bucket is None:
                bucket = {"artifacts": {}}
            try:
                yield bucket
            finally:
                save_bucket(store_key, bucket)
        else:
            b = _by_request.setdefault(store_key, {"artifacts": {}})
            try:
                yield b
            finally:
                arts_fm = b.get("artifacts") or {}
                if not arts_fm and store_key in _by_request:
                    del _by_request[store_key]


def maybe_refresh_workspace_metrics() -> None:
    """Chamado em GET /metrics (throttle). Apaga expirados em postgres e actualiza gauges."""
    global _metrics_last_monotonic
    now = time.monotonic()
    if now - _metrics_last_monotonic < _METRICS_MIN_INTERVAL:
        return
    _metrics_last_monotonic = now
    if _use_postgres():
        refresh_postgres_workspace_metrics_sync()
    else:
        refresh_memory_workspace_metrics_sync()


def refresh_postgres_workspace_metrics_sync() -> None:
    delete_expired_sessions()
    n, nbytes = count_and_payload_bytes()
    WORKSPACE_SESSIONS.set(float(n))
    WORKSPACE_PAYLOAD_BYTES.set(float(nbytes))


def refresh_memory_workspace_metrics_sync() -> None:
    with _lock:
        n = len(_by_request)
        total = 0
        for b in _by_request.values():
            try:
                total += len(json.dumps(b, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError):
                total += 0
    WORKSPACE_SESSIONS.set(float(n))
    WORKSPACE_PAYLOAD_BYTES.set(float(total))


def _valid_artifact_type(raw: str) -> str:
    if raw in ("markdown", "plain", "json", "text"):
        return raw
    return "plain"


def _sanitize_title(raw: str | None) -> str:
    if not raw or not isinstance(raw, str):
        return "Artefacto"
    t = raw.strip()
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    if len(t) > _MAX_TITLE_LEN:
        t = t[:_MAX_TITLE_LEN - 1] + "…"
    return t if t else "Artefacto"


def _check_canvas_write_gate(
    art: dict[str, Any] | None,
    write_ctx: dict[str, Any] | None,
) -> dict[str, str] | None:
    """G6 v1: mutações só pelo slot activo se coincidir com ``created_by_slot`` do artefacto."""
    if not write_ctx or not bool(write_ctx.get("enforce_slot_write")):
        return None
    if not art:
        return None
    default = max(1, min(4, int(write_ctx.get("default_slot", 1))))
    try:
        owner = int(art.get("created_by_slot", default))
    except (TypeError, ValueError):
        owner = default
    owner = max(1, min(4, owner))
    try:
        active = int(write_ctx.get("active_slot", default))
    except (TypeError, ValueError):
        active = default
    active = max(1, min(4, active))
    if owner != active:
        return {
            "error": "canvas_write_forbidden",
            "message": (
                f"Artifact is owned by slot {owner}; only active slot {active} may edit (G6)."
            ),
        }
    return None


def _snapshot(
    aid: str,
    slot: dict[str, Any],
    *,
    write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "artifact_id": aid,
        "title": str(slot.get("title", "Artefacto")),
        "artifact_type": str(slot.get("artifact_type", "plain")),
        "content": str(slot.get("content", "")),
        "revision": int(slot.get("revision", 0)),
    }
    if write_ctx is not None:
        ds = max(1, min(4, int(write_ctx.get("default_slot", 1))))
        raw_owner = slot.get("created_by_slot")
        try:
            own_i = int(raw_owner) if raw_owner is not None else ds
        except (TypeError, ValueError):
            own_i = ds
        own_i = max(1, min(4, own_i))
        edges = write_ctx.get("edges") or []
        if not isinstance(edges, list):
            edges = []
        out["schema_version"] = 1
        out["slot"] = own_i
        from app.shared.canvas_write_context import group_id_from_edges

        out["group_id"] = group_id_from_edges([e for e in edges if isinstance(e, dict)], own_i)
    return out


def _artifact_ids_with_content(arts: dict[str, Any]) -> list[str]:
    return [k for k, v in arts.items() if v and str(v.get("content", ""))]


def _resolve_patch_artifact_id(
    explicit: str,
    arts: dict[str, Any],
) -> tuple[str | None, dict[str, str] | None]:
    """Resolve o id alvo do patch.

    ``explicit`` — valor já normalizado (strip) de ``arguments["artifact_id"]`` ou ``""`` se omitido.

    Retorno: ``(artifact_id, None)`` ou ``(None, {"error": ..., "message": ...})``.
    """
    if explicit:
        slot = arts.get(explicit)
        if not slot or not str(slot.get("content", "")):
            return None, {
                "error": "no_artifact",
                "message": "Artifact empty or not found; create or replace content first",
            }
        return explicit, None

    keys = _artifact_ids_with_content(arts)
    if len(keys) == 0:
        return None, {
            "error": "no_artifact",
            "message": "No workspace artifact with content; call manage_workspace_artifact first",
        }
    if len(keys) > 1:
        return None, {
            "error": "ambiguous_artifact",
            "message": "Multiple artifacts; include artifact_id from TOOL_RESULT",
        }
    return keys[0], None


def manage_workspace_artifact(
    request_id: str,
    arguments: dict[str, Any],
    *,
    write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = str(arguments.get("action", "")).strip().lower()
    if action == "create":
        title = _sanitize_title(arguments.get("title") if isinstance(arguments.get("title"), str) else None)
        at = _valid_artifact_type(str(arguments.get("artifact_type", "plain")).strip().lower())
        content = arguments.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        if len(content) > _MAX_CONTENT_CHARS:
            return {
                "ok": False,
                "error": "content_too_large",
                "message": f"content exceeds {_MAX_CONTENT_CHARS} characters",
            }
        aid = str(uuid.uuid4())
        with _bucket_transaction(request_id) as b:
            arts: dict[str, Any] = b["artifacts"]
            row: dict[str, Any] = {
                "title": title,
                "artifact_type": at,
                "content": content,
                "revision": 1,
            }
            if write_ctx is not None:
                try:
                    row["created_by_slot"] = max(1, min(4, int(write_ctx.get("active_slot", 1))))
                except (TypeError, ValueError):
                    row["created_by_slot"] = 1
            arts[aid] = row
            slot = arts[aid]
            snap = _snapshot(aid, slot, write_ctx=write_ctx)
        return {
            "ok": True,
            "action": "create",
            "artifact_id": aid,
            "artifact_type": snap["artifact_type"],
            "revision": snap["revision"],
            "content_length": len(snap["content"]),
            "canvas": snap,
        }

    if action == "replace":
        aid = str(arguments.get("artifact_id", "")).strip()
        content = arguments.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        if len(content) > _MAX_CONTENT_CHARS:
            return {
                "ok": False,
                "error": "content_too_large",
                "message": f"content exceeds {_MAX_CONTENT_CHARS} characters",
            }
        if not aid:
            return {
                "ok": False,
                "error": "missing_artifact_id",
                "message": "artifact_id is required for replace",
            }
        title_upd = arguments.get("title")
        with _bucket_transaction(request_id) as b:
            arts = b.get("artifacts") or {}
            if not arts:
                return {
                    "ok": False,
                    "error": "unknown_artifact",
                    "message": "No workspace artifacts for this request",
                }
            slot = arts.get(aid)
            if not slot:
                return {
                    "ok": False,
                    "error": "no_artifact",
                    "message": "artifact_id not found for this request",
                }
            gate = _check_canvas_write_gate(slot, write_ctx)
            if gate:
                return {"ok": False, **gate}
            slot["content"] = content
            slot["revision"] = int(slot.get("revision", 0)) + 1
            if isinstance(title_upd, str) and title_upd.strip():
                slot["title"] = _sanitize_title(title_upd)
            snap = _snapshot(aid, slot, write_ctx=write_ctx)
        return {
            "ok": True,
            "action": "replace",
            "artifact_id": aid,
            "artifact_type": snap["artifact_type"],
            "revision": snap["revision"],
            "content_length": len(snap["content"]),
            "canvas": snap,
        }

    return {
        "ok": False,
        "error": "invalid_action",
        "message": 'action must be "create" or "replace"',
    }


def apply_canvas_patch(
    request_id: str,
    arguments: dict[str, Any],
    *,
    write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sb = arguments.get("search_block")
    rb = arguments.get("replace_block")
    if not isinstance(sb, str) or not isinstance(rb, str):
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": "search_block and replace_block must be strings",
        }
    if not sb:
        return {
            "ok": False,
            "error": "empty_search",
            "message": "search_block must be non-empty",
        }

    raw_aid = arguments.get("artifact_id")
    explicit = str(raw_aid).strip() if raw_aid is not None else ""

    with _bucket_transaction(request_id) as b:
        arts: dict[str, Any] = b.get("artifacts") or {}
        if not arts:
            return {
                "ok": False,
                "error": "unknown_artifact",
                "message": "No workspace artifacts for this request",
            }
        aid, err = _resolve_patch_artifact_id(explicit, arts)
        if err:
            return {"ok": False, **err}
        slot = arts.get(aid)
        if not slot:
            return {
                "ok": False,
                "error": "no_artifact",
                "message": "Artifact empty or not found; create or replace content first",
            }
        gate = _check_canvas_write_gate(slot, write_ctx)
        if gate:
            return {"ok": False, **gate}
        text = str(slot["content"])
        count = text.count(sb)
        if count == 0:
            return {
                "ok": False,
                "error": "search_not_found",
                "message": "search_block not found in artifact",
            }
        if count > 1:
            return {
                "ok": False,
                "error": "ambiguous_search",
                "message": f"search_block matches {count} occurrences; narrow the anchor",
            }
        new_text = text.replace(sb, rb, 1)
        slot["content"] = new_text
        slot["revision"] = int(slot.get("revision", 0)) + 1
        snap = _snapshot(aid, slot, write_ctx=write_ctx)

    return {
        "ok": True,
        "artifact_id": aid,
        "revision": snap["revision"],
        "content_length": len(snap["content"]),
        "canvas": snap,
    }


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_workspace = APIRouter()


# ── Models ──

class WidgetSlotGraphEdgeIn(BaseModel):
    slot_a: int = Field(..., ge=1, le=4)
    slot_b: int = Field(..., ge=1, le=4)


class WidgetSlotGraphPatchBody(BaseModel):
    """Actualização optimista do grafo simétrico entre slots 1–4."""

    version: int = Field(..., ge=0, description="Versão actual lida em GET; mismatch devolve 409.")
    edges: list[WidgetSlotGraphEdgeIn] = Field(default_factory=list)
    preset: str | None = Field(
        default=None,
        description="Opcional: isolated | full | example_1_4 — substitui `edges` quando definido.",
        max_length=64,
    )


# ── Routes: Slot Graph ──

@router_workspace.get("/ui/widget_slot_graph", tags=["WidgetMVP"])
def ui_widget_slot_graph_get() -> dict[str, Any]:
    """Grafo simétrico 1–4 (SSOT). Desligado: `enabled=false` sem 404."""
    if not WIDGET_MULTI_SLOT_ENABLED:
        return {"enabled": False, "slots": 4, "version": 0, "edges": []}
    g = load_widget_slot_graph()
    return {"enabled": True, "slots": 4, "version": g.get("version", 0), "edges": g.get("edges", [])}


@router_workspace.patch("/ui/widget_slot_graph", tags=["WidgetMVP"])
def ui_widget_slot_graph_patch(payload: WidgetSlotGraphPatchBody) -> dict[str, Any]:
    if not WIDGET_MULTI_SLOT_ENABLED:
        raise HTTPException(status_code=404, detail="widget_multi_slot_disabled")
    edges_in: list[dict[str, Any]]
    if (payload.preset or "").strip():
        edges_in = list(apply_preset(str(payload.preset)))
    else:
        edges_in = [e.model_dump() for e in payload.edges]
    new_state = replace_widget_slot_graph(expected_version=int(payload.version), edges=edges_in)
    if new_state is None:
        cur = load_widget_slot_graph()
        raise HTTPException(status_code=409, detail={"error": "version_conflict", "current": cur})
    return {"enabled": True, "slots": 4, "version": new_state["version"], "edges": new_state["edges"]}
