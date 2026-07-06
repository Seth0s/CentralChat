"""Sessions domain — chat sessions CRUD, event log, session summaries, preferences.

Consolidated from:
  - shared/chat_sessions.py               (session store, event log, message projection)
  - session_summary_store.py              (PG session summaries)
  - sessions.py                           (API router)
  - repositories/chat_sessions_repository.py (re-export shim)
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import (
    CENTRAL_DEFAULT_CLIENT_ID,
    CENTRAL_FOCUS_MODE,
    CENTRAL_MULTISLOT_DEFAULT_SLOT,
    CHAT_SESSIONS_ENABLED,
    CHAT_SESSIONS_EVENT_LOG_ENABLED,
    CHAT_SESSIONS_LEGACY_JSON,
    CHAT_SESSIONS_MAX_MESSAGES,
    CHAT_SESSIONS_MAX_SESSIONS,
    CHAT_SESSIONS_STORE_PATH,
    WIDGET_MULTI_SLOT_ENABLED,
)
from app.domain.chat_sessions_domain import normalize_session_title, truncate_title
from app.repositories.preferences_repository import load_preferences, merge_preferences_patch
from app.repositories.session_event_store import SessionEventStore
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

# ═══════════════════════════════════════════════════════════════════
# SESSION STORE (event log + JSON fallback)
# ═══════════════════════════════════════════════════════════════════

_lock = threading.Lock()
_store = SessionEventStore()
_projection = None
_migration_done = False


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_projection():
    global _projection
    if _projection is None:
        from app.context import LinearTranscriptProjection

        _projection = LinearTranscriptProjection()
    return _projection


def _tenant_id() -> str:
    from app.shared.tenant_context import get_current_client_id

    cid = get_current_client_id()
    return (cid or CENTRAL_DEFAULT_CLIENT_ID).strip() or CENTRAL_DEFAULT_CLIENT_ID


def _store_path() -> Path:
    from app.shared.tenant_paths import resolve_chat_sessions_path

    return resolve_chat_sessions_path(CHAT_SESSIONS_STORE_PATH)


def _empty_root() -> dict[str, Any]:
    return {"schema": 1, "sessions": []}


def _load_unlocked() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return _empty_root()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
            return _empty_root()
        return data
    except Exception:
        return _empty_root()


def _save_unlocked(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _ensure_migrated_unlocked(data: dict[str, Any]) -> None:
    global _migration_done
    if not CHAT_SESSIONS_EVENT_LOG_ENABLED:
        return
    if _migration_done:
        return
    from app.context import migrate_legacy_chat_sessions

    migrate_legacy_chat_sessions(tenant_id=_tenant_id(), legacy_root=data, store=_store)
    _migration_done = True


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cap = max(4, CHAT_SESSIONS_MAX_MESSAGES)
    if len(messages) <= cap:
        return messages
    return messages[-cap:]


def _trim_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cap = max(1, CHAT_SESSIONS_MAX_SESSIONS)
    if len(sessions) <= cap:
        return sessions

    def key(s: dict[str, Any]) -> str:
        return str(s.get("updated_at") or "")

    sorted_s = sorted(sessions, key=key)
    return sorted_s[-cap:]


def _session_pinned(s: dict[str, Any]) -> bool:
    return bool(s.get("pinned"))


def _normalize_messages(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip().lower()
        content = str(row.get("content") or "")
        if role not in ("user", "assistant"):
            continue
        out.append({"role": role, "content": content})
    return out


def _messages_for_session(session_id: str, *, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    if not CHAT_SESSIONS_EVENT_LOG_ENABLED:
        return fallback
    events = _store.list_for_session(_tenant_id(), session_id)
    if not events:
        return fallback
    if WIDGET_MULTI_SLOT_ENABLED and not CENTRAL_FOCUS_MODE:
        from app.context import ContextGraphProjection
        from app.workspace import load_widget_slot_graph

        return ContextGraphProjection().transcript_from_events(
            events,
            slot_graph=load_widget_slot_graph(),
            default_slot=CENTRAL_MULTISLOT_DEFAULT_SLOT,
        )
    return _get_projection().project(events)


def _session_api_extras(session_id: str) -> dict[str, Any]:
    """Optional fields for UI (summary_version, schema_version) — no PII."""
    extras: dict[str, Any] = {
        "schema_version": 2 if CHAT_SESSIONS_EVENT_LOG_ENABLED else 1,
    }
    try:
        if memory_db_enabled():
            row = get_latest_session_summary(
                tenant_id=resolve_pg_tenant_id(),
                session_id=session_id,
            )
            if row is not None:
                extras["summary_version"] = int(row.version)
    except Exception:
        pass
    return extras


def _sync_session_messages(data: dict[str, Any], session_id: str) -> None:
    sid = (session_id or "").strip()
    for s in data.get("sessions", []):
        if isinstance(s, dict) and str(s.get("id")) == sid:
            if CHAT_SESSIONS_EVENT_LOG_ENABLED and not CHAT_SESSIONS_LEGACY_JSON:
                s["messages"] = []
            else:
                fallback = _normalize_messages(s.get("messages"))
                s["messages"] = _trim_messages(_messages_for_session(sid, fallback=fallback))
            break


def list_sessions_meta() -> list[dict[str, Any]]:
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        out: list[dict[str, Any]] = []
        kept_sessions: list[dict[str, Any]] = []
        sessions_before = len(data.get("sessions", []))
        tenant = _tenant_id()
        for s in data.get("sessions", []):
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "")
            if len(sid) < 8:
                continue
            if CHAT_SESSIONS_EVENT_LOG_ENABLED:
                _sync_session_messages(data, sid)
            msgs = _messages_for_session(sid, fallback=_normalize_messages(s.get("messages")))
            n = len(msgs)
            pinned = _session_pinned(s)
            kept_sessions.append(s)
            out.append(
                {
                    "id": sid,
                    "title": str(s.get("title") or "Conversa"),
                    "created_at": str(s.get("created_at") or ""),
                    "updated_at": str(s.get("updated_at") or ""),
                    "message_count": n,
                    "pinned": pinned,
                    **_session_api_extras(sid),
                }
            )
        data["sessions"] = _trim_sessions(kept_sessions)
        if CHAT_SESSIONS_EVENT_LOG_ENABLED or len(kept_sessions) != sessions_before:
            _save_unlocked(data)
        pinned_rows = [x for x in out if x["pinned"]]
        unpinned = [x for x in out if not x["pinned"]]
        pinned_rows.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        unpinned.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        return pinned_rows + unpinned


def get_session(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return None
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        for s in data.get("sessions", []):
            if isinstance(s, dict) and str(s.get("id")) == sid:
                msgs = _messages_for_session(sid, fallback=_normalize_messages(s.get("messages")))
                if CHAT_SESSIONS_EVENT_LOG_ENABLED:
                    s["messages"] = _trim_messages(msgs)
                    _save_unlocked(data)
                return {
                    "id": sid,
                    "title": str(s.get("title") or "Conversa"),
                    "pinned": _session_pinned(s),
                    "updated_at": str(s.get("updated_at") or ""),
                    "messages": msgs,
                    **_session_api_extras(sid),
                }
    return None


def create_session(*, title: str | None) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    now = _utc_iso()
    t = normalize_session_title(title)
    entry = {"id": sid, "title": t, "pinned": False, "created_at": now, "updated_at": now, "messages": []}
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        sessions = [x for x in data.get("sessions", []) if isinstance(x, dict)]
        sessions.append(entry)
        data["sessions"] = _trim_sessions(sessions)
        _save_unlocked(data)
    row = {"id": sid, "title": t, "pinned": False, "created_at": now, "updated_at": now, "messages": []}
    row.update(_session_api_extras(sid))
    return row


def delete_session(session_id: str) -> bool:
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return False
    with _lock:
        data = _load_unlocked()
        sessions = [x for x in data.get("sessions", []) if isinstance(x, dict)]
        new_list = [x for x in sessions if str(x.get("id")) != sid]
        if len(new_list) == len(sessions):
            return False
        data["sessions"] = new_list
        _save_unlocked(data)
        if CHAT_SESSIONS_EVENT_LOG_ENABLED:
            _store.delete_session(_tenant_id(), sid)
    return True


def patch_session(session_id: str, *, title: str | None = None, pinned: bool | None = None) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return None
    if title is None and pinned is None:
        return None
    now = _utc_iso()
    new_title: str | None = None
    if title is not None:
        new_title = truncate_title(title)
        if len(new_title) < 1:
            return None
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        for s in data.get("sessions", []):
            if isinstance(s, dict) and str(s.get("id")) == sid:
                if new_title is not None:
                    s["title"] = new_title
                if pinned is not None:
                    s["pinned"] = bool(pinned)
                s["updated_at"] = now
                msgs = _messages_for_session(sid, fallback=_normalize_messages(s.get("messages")))
                if CHAT_SESSIONS_EVENT_LOG_ENABLED:
                    s["messages"] = _trim_messages(msgs)
                _save_unlocked(data)
                return {
                    "id": sid,
                    "title": str(s.get("title") or "Conversa"),
                    "pinned": _session_pinned(s),
                    "updated_at": now,
                    "messages": msgs,
                    **_session_api_extras(sid),
                }
    return None


def rename_session(session_id: str, *, title: str) -> dict[str, Any] | None:
    return patch_session(session_id, title=title)


def history_dicts_for_prepare(session_id: str) -> list[dict[str, str]] | None:
    """Mensagens concluídas (sem o turno actual — o utilizador vai em `text`)."""
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return None
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        for s in data.get("sessions", []):
            if isinstance(s, dict) and str(s.get("id")) == sid:
                fallback = _normalize_messages(s.get("messages"))
                return _messages_for_session(sid, fallback=fallback)
    return None


def append_completed_turn(
    session_id: str,
    *,
    user_text: str,
    assistant_text: str,
    active_slot: int | None = None,
) -> bool:
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return False
    now = _utc_iso()
    u = (user_text or "").strip()
    a = assistant_text or ""
    with _lock:
        data = _load_unlocked()
        _ensure_migrated_unlocked(data)
        sessions = [x for x in data.get("sessions", []) if isinstance(x, dict)]
        found = False
        for s in sessions:
            if str(s.get("id")) != sid:
                continue
            found = True
            if CHAT_SESSIONS_EVENT_LOG_ENABLED:
                slot: int | None = None
                if active_slot is not None:
                    try:
                        slot_val = int(active_slot)
                        if 1 <= slot_val <= 4:
                            slot = slot_val
                    except (TypeError, ValueError):
                        slot = None
                _store.append_turn(
                    tenant_id=_tenant_id(),
                    session_id=sid,
                    user_text=u,
                    assistant_text=a,
                    slot=slot,
                )
                if CHAT_SESSIONS_LEGACY_JSON:
                    msgs = _trim_messages(_messages_for_session(sid, fallback=[]))
                    s["messages"] = msgs
                else:
                    s["messages"] = []
            else:
                msgs = _normalize_messages(s.get("messages"))
                msgs.append({"role": "user", "content": u})
                msgs.append({"role": "assistant", "content": a})
                s["messages"] = _trim_messages(msgs)
            s["updated_at"] = now
            if (str(s.get("title") or "").strip() in ("", "Nova conversa")) and u:
                s["title"] = u[:80] + ("…" if len(u) > 80 else "")
            break
        if not found:
            return False
        data["sessions"] = _trim_sessions(sessions)
        _save_unlocked(data)
    try:
        from app.rag import ingest_session_turn_facts

        ingest_session_turn_facts(
            chat_session_id=sid,
            user_text=u,
            assistant_text=a,
            tenant_id=_tenant_id(),
        )
    except Exception:
        pass
    return True


# ═══════════════════════════════════════════════════════════════════
# SUMMARY STORE (PG per-session rolling summaries)
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SessionSummaryRow:
    tenant_id: str
    session_id: str
    version: int
    summary_text: str
    covers_event_id_until: str | None
    provenance: str
    request_id: str | None


def _resolve_summary_tenant(*, tenant_id: str | None = None) -> str:
    if tenant_id and str(tenant_id).strip():
        return str(tenant_id).strip()
    return resolve_pg_tenant_id()


def ensure_session_summaries_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_summaries (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id TEXT NOT NULL DEFAULT 'default',
                  session_id TEXT NOT NULL,
                  version INT NOT NULL,
                  summary_text TEXT NOT NULL,
                  covers_event_id_until TEXT,
                  request_id TEXT,
                  provenance TEXT NOT NULL DEFAULT 'eco_summarizer',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (tenant_id, session_id, version)
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS session_summaries_tenant_session_version
                ON session_summaries (tenant_id, session_id, version DESC);
                """
            )
            cur.execute("ALTER TABLE IF EXISTS session_summaries ENABLE ROW LEVEL SECURITY;")
            cur.execute("DROP POLICY IF EXISTS session_summaries_tenant_rls ON session_summaries;")
            cur.execute(
                """
                CREATE POLICY session_summaries_tenant_rls ON session_summaries
                  USING (tenant_id = current_setting('app.tenant_id', true))
                  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
                """
            )


def get_latest_session_summary(
    *,
    tenant_id: str | None,
    session_id: str,
) -> SessionSummaryRow | None:
    if not memory_db_enabled():
        return None
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return None
    tid = _resolve_summary_tenant(tenant_id=tenant_id)
    ensure_session_summaries_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tenant_id, session_id, version, summary_text,
                       covers_event_id_until, provenance, request_id
                FROM session_summaries
                WHERE tenant_id = %s AND session_id = %s
                ORDER BY version DESC
                LIMIT 1;
                """,
                (tid, sid),
            )
            row = cur.fetchone()
            if not row:
                return None
            return SessionSummaryRow(
                tenant_id=str(row[0]),
                session_id=str(row[1]),
                version=int(row[2]),
                summary_text=str(row[3] or ""),
                covers_event_id_until=str(row[4]) if row[4] else None,
                provenance=str(row[5] or "eco_summarizer"),
                request_id=str(row[6]) if row[6] else None,
            )


def insert_session_summary(
    *,
    tenant_id: str | None,
    session_id: str,
    summary_text: str,
    covers_event_id_until: str | None = None,
    request_id: str | None = None,
    provenance: str = "eco_summarizer",
) -> SessionSummaryRow | None:
    if not memory_db_enabled():
        return None
    sid = (session_id or "").strip()
    text = (summary_text or "").strip()
    if len(sid) < 8 or not text:
        return None
    tid = _resolve_summary_tenant(tenant_id=tenant_id)
    ensure_session_summaries_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM session_summaries
                WHERE tenant_id = %s AND session_id = %s;
                """,
                (tid, sid),
            )
            ver_row = cur.fetchone()
            version = int(ver_row[0]) if ver_row and ver_row[0] is not None else 1
            cur.execute(
                """
                INSERT INTO session_summaries
                  (tenant_id, session_id, version, summary_text,
                   covers_event_id_until, request_id, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    tid,
                    sid,
                    version,
                    text,
                    covers_event_id_until,
                    request_id,
                    (provenance or "eco_summarizer")[:64],
                ),
            )
    return SessionSummaryRow(
        tenant_id=tid,
        session_id=sid,
        version=version,
        summary_text=text,
        covers_event_id_until=covers_event_id_until,
        provenance=provenance,
        request_id=request_id,
    )


def count_session_summaries(*, tenant_id: str | None = None, session_id: str | None = None) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_summary_tenant(tenant_id=tenant_id)
    ensure_session_summaries_schema()
    with connect_pg(tenant_id=tid) as conn:
        with conn.cursor() as cur:
            if session_id and session_id.strip():
                cur.execute(
                    "SELECT COUNT(*) FROM session_summaries WHERE tenant_id = %s AND session_id = %s;",
                    (tid, session_id.strip()),
                )
            else:
                cur.execute(
                    "SELECT COUNT(*) FROM session_summaries WHERE tenant_id = %s;",
                    (tid,),
                )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_sessions = APIRouter()


# ── Helpers ──

def _require_chat_sessions_api() -> None:
    if not CHAT_SESSIONS_ENABLED:
        raise HTTPException(status_code=404, detail="not_found")


# ── Models ──

class AssistantPreferencesPatchRequest(BaseModel):
    """PATCH parcial; campos omitidos mantêm-se."""

    verbosity: str | None = None
    tone_hint: str | None = None
    inference_destination: str | None = Field(default=None, description="local | api")
    llm_model_id: str | None = Field(default=None, max_length=256)
    auto_tier: str | None = Field(
        default=None,
        description="economy | balanced | premium — vazio limpa; só em inference_destination=api",
        max_length=32,
    )
    aux_llm_destination: str | None = Field(default=None, description="local | api")
    aux_llm_model_id: str | None = Field(default=None, max_length=256)
    embedding_destination: str | None = Field(default=None, description="local | api")
    embedding_model_id: str | None = Field(default=None, max_length=128)
    default_include_long_session_memory: bool | None = None
    default_include_memory_recall: bool | None = None
    default_include_host_context: bool | None = None
    default_include_playbook: bool | None = None
    default_include_capability_digest: bool | None = None
    default_use_agent_tools: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="LLM temperature 0.0-2.0")
    effort: str | None = Field(default=None, max_length=16, description="Reasoning effort: low|medium|high")
    provider_routing: str | None = Field(default=None, max_length=32, description="OpenRouter routing: cheapest|fastest|throughput")
    thinking_budget: int | None = Field(default=None, ge=0, description="Anthropic extended thinking budget in tokens")


class ChatSessionCreateBody(BaseModel):
    title: str | None = Field(None, max_length=120)


class ChatSessionPatchBody(BaseModel):
    """Actualização parcial da sessão: pelo menos um campo."""

    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class InterruptRespondBody(BaseModel):
    choice: str | None = Field(default=None, max_length=500)
    custom: str | None = Field(default=None, max_length=2000)


# ── Routes: Sidebar (consolidated) ──

@router_sessions.get("/ui/sidebar", tags=["WidgetMVP"])
def ui_sidebar() -> dict[str, Any]:
    """Consolidated sidebar data — single call replaces GetWorkspace + GetPreferences + GetUsage + ListWorkItems + ListApprovals."""
    tid = resolve_pg_tenant_id()

    # Workspace
    ws_data: dict[str, Any] = {"path": None, "branch": None, "dirty_count": 0}
    try:
        from app.workspace_service import get_workspace_binding, git_metadata as ws_git

        binding = get_workspace_binding(tenant_id=tid)
        if binding and binding.get("path"):
            p = str(binding["path"])
            ws_data["path"] = p
            ws_data["connector_id"] = binding.get("connector_id")
            try:
                g = ws_git(p)
                ws_data["branch"] = g.get("branch", "")
                ws_data["dirty_count"] = int(g.get("dirty_count", 0))
            except Exception:
                pass
    except Exception:
        pass

    # Preferences (model, inference_dest, auto_tier, temperature, effort, max_tokens)
    prefs_data: dict[str, Any] = {}
    try:
        p = load_preferences()
        prefs_data["model"] = p.get("llm_model_id", "")
        prefs_data["inference_dest"] = p.get("inference_destination", "api")
        prefs_data["auto_tier"] = p.get("auto_tier", "")
        prefs_data["temperature"] = p.get("temperature")
        prefs_data["effort"] = p.get("effort")
        prefs_data["max_tokens"] = p.get("max_tokens")
    except Exception:
        pass

    # Usage
    usage_data: dict[str, Any] = {"total_cost": 0}
    try:
        from app.tenant_quota import query_tenant_quota_snapshot

        snap = query_tenant_quota_snapshot(tid)
        if snap:
            usage_data["total_cost"] = getattr(snap, "usd_cost", 0) or 0
    except Exception:
        pass

    # Approvals pending count
    pending = 0
    try:
        from app.shared.approvals_store import count_pending

        pending = count_pending(tenant_id=tid)
    except Exception:
        pass

    # Work items
    wq_count = 0
    try:
        from app.work_items import count_work_items

        wq_count = count_work_items(tenant_id=tid)
    except Exception:
        pass

    # Connector status
    connector: dict[str, Any] = {"online": False, "count": 0}
    try:
        from app.connector import build_connector_status_public_snapshot

        cs = build_connector_status_public_snapshot(tenant_id=tid)
        connector = {"online": cs.get("online", False), "count": cs.get("connector_count", 0)}
    except Exception:
        pass

    return {
        "workspace": ws_data,
        "preferences": prefs_data,
        "usage": usage_data,
        "pending_approvals": pending,
        "work_queue_count": wq_count,
        "connector": connector,
    }


# ── Routes: Preferences ──

@router_sessions.get("/ui/preferences", tags=["WidgetMVP", "OpsDashboard"])
def ui_preferences_get() -> dict[str, Any]:
    """L2: preferências locais (sem segredos)."""
    return {"assistant_preferences": load_preferences()}


@router_sessions.post("/ui/preferences", tags=["WidgetMVP", "OpsDashboard"])
def ui_preferences_set(payload: AssistantPreferencesPatchRequest) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_unset=True)
        data = merge_preferences_patch(patch)
        return {"assistant_preferences": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Routes: Chat Sessions ──

@router_sessions.get("/ui/chat-sessions", tags=["WidgetMVP"])
def ui_chat_sessions_list() -> dict[str, Any]:
    if not CHAT_SESSIONS_ENABLED:
        return {"items": [], "chat_sessions_enabled": False}
    return {"items": list_sessions_meta(), "chat_sessions_enabled": True}


@router_sessions.post("/ui/chat-sessions", tags=["WidgetMVP"])
def ui_chat_sessions_create(body: ChatSessionCreateBody) -> dict[str, Any]:
    _require_chat_sessions_api()
    s = create_session(title=body.title)
    return {"session": s}


@router_sessions.get("/ui/chat-sessions/{session_id}", tags=["WidgetMVP"])
def ui_chat_sessions_get(session_id: str) -> dict[str, Any]:
    _require_chat_sessions_api()
    row = get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return {"session": row}


@router_sessions.patch("/ui/chat-sessions/{session_id}", tags=["WidgetMVP"])
def ui_chat_sessions_patch(session_id: str, payload: ChatSessionPatchBody) -> dict[str, Any]:
    _require_chat_sessions_api()
    if payload.title is None and payload.pinned is None:
        raise HTTPException(
            status_code=422,
            detail="body must include at least one of: title, pinned",
        )
    title_arg: str | None = None
    if payload.title is not None:
        t = (payload.title or "").strip()
        if len(t) < 1:
            raise HTTPException(status_code=422, detail="title must be at least 1 non-whitespace character")
        title_arg = t
    row = patch_session(session_id, title=title_arg, pinned=payload.pinned)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return {"session": row}


@router_sessions.delete("/ui/chat-sessions/{session_id}", tags=["WidgetMVP"])
def ui_chat_sessions_delete(session_id: str) -> dict[str, Any]:
    _require_chat_sessions_api()
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router_sessions.get("/ui/sessions/{session_id}/surface", tags=["WidgetMVP"])
def ui_session_surface(session_id: str) -> dict[str, Any]:
    _require_chat_sessions_api()
    from app.session_surface_service import build_surface_snapshot

    snap = build_surface_snapshot(session_id)
    if not snap:
        raise HTTPException(status_code=404, detail="not_found")
    return snap


@router_sessions.post(
    "/ui/sessions/{session_id}/interrupts/{interrupt_id}/respond",
    tags=["WidgetMVP"],
)
def ui_interrupt_respond(
    session_id: str,
    interrupt_id: str,
    body: InterruptRespondBody,
) -> dict[str, Any]:
    _require_chat_sessions_api()
    from app.session_surface_service import respond_interrupt_http

    try:
        return respond_interrupt_http(
            session_id,
            interrupt_id,
            choice=body.choice,
            custom=body.custom,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code in ("no_active_interrupt", "interrupt_mismatch", "session_not_found") else 400
        raise HTTPException(status_code=status, detail=code) from exc
