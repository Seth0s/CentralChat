"""Playbook domain — CRUD, export, promotion candidates, feedback, RAG context.

Consolidated from:
  - playbook_store.py                (store, RAG léxico, feedback)
  - playbook_promotion_candidates.py (governed promotion from approved executions)
  - playbook_routes.py               (API router)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from app.config import (
    CENTRAL_FOCUS_MODE,
    PLAYBOOK_FEATURE_ENABLED,
    PLAYBOOK_FEEDBACK_LOG_MAX_EVENTS,
    PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED,
    PLAYBOOK_MAX_BLOCK_CHARS,
    PLAYBOOK_MAX_SNIPPETS_RETRIEVAL,
    PLAYBOOK_PROMOTION_CANDIDATES_PATH,
    PLAYBOOK_STORE_PATH,
)
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit
from app.shared.approvals_store import get_approval, resolve_tenant_id_for_store

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# STORE
# ═══════════════════════════════════════════════════════════════════

_PROVENANCE_MANUAL = "manual"
_TITLE_MAX = 200
_BODY_MAX = 8000
_TAG_MAX_LEN = 64
_TAG_MAX_COUNT = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _store_path() -> Path:
    return Path(PLAYBOOK_STORE_PATH)


def _feedback_path() -> Path:
    p = _store_path()
    return p.parent / "assistant_playbook_feedback.json"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "entries": []}


def load_playbook_store() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return _empty_store()
    return {"version": int(raw.get("version") or 1), "entries": entries}


def _save_playbook_store(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_iso(dt: str | None) -> datetime | None:
    if not dt or not isinstance(dt, str):
        return None
    try:
        if dt.endswith("Z"):
            dt = dt[:-1] + "+00:00"
        return datetime.fromisoformat(dt)
    except ValueError:
        return None


def _is_expired(entry: dict[str, Any]) -> bool:
    exp = _parse_iso(str(entry.get("expires_at") or "") or None)
    if exp is None:
        return False
    return _utcnow() > exp


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    for t in tags[:_TAG_MAX_COUNT]:
        if not isinstance(t, str):
            continue
        s = t.strip()[:_TAG_MAX_LEN]
        if s:
            out.append(s)
    return out


def list_playbook_entries_meta(*, include_expired: bool = False) -> list[dict[str, Any]]:
    """Lista curta para UI (sem corpo longo)."""
    data = load_playbook_store()
    rows: list[dict[str, Any]] = []
    for e in data.get("entries", []):
        if not isinstance(e, dict):
            continue
        if not include_expired and _is_expired(e):
            continue
        rows.append(
            {
                "id": str(e.get("id", "")),
                "title": str(e.get("title", "")),
                "tags": e.get("tags") if isinstance(e.get("tags"), list) else [],
                "provenance": str(e.get("provenance", "")),
                "created_at": str(e.get("created_at", "")),
                "expires_at": e.get("expires_at"),
                "helpful_votes": int(e.get("helpful_votes") or 0),
                "not_helpful_votes": int(e.get("not_helpful_votes") or 0),
                "body_preview": (str(e.get("body", ""))[:160] + "…")
                if len(str(e.get("body", ""))) > 160
                else str(e.get("body", "")),
            }
        )
    return rows


def get_playbook_entry(entry_id: str) -> dict[str, Any] | None:
    for e in load_playbook_store().get("entries", []):
        if isinstance(e, dict) and str(e.get("id")) == entry_id:
            return e
    return None


def add_playbook_entry_manual(
    *,
    title: str,
    body: str,
    tags: list[str] | None,
    ttl_days: int | None,
) -> dict[str, Any]:
    """Curadoria humana — única proveniência gravável pela API pública."""
    t = title.strip()
    b = body.strip()
    if not t or len(t) > _TITLE_MAX:
        raise ValueError("title_invalid")
    if not b or len(b) > _BODY_MAX:
        raise ValueError("body_invalid")
    now = _utcnow()
    expires_at: str | None = None
    if ttl_days is not None:
        if ttl_days < 1 or ttl_days > 3650:
            raise ValueError("ttl_invalid")
        expires_at = (now + timedelta(days=ttl_days)).isoformat()
    entry = {
        "id": str(uuid.uuid4()),
        "title": t,
        "body": b,
        "tags": _normalize_tags(tags),
        "provenance": _PROVENANCE_MANUAL,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "helpful_votes": 0,
        "not_helpful_votes": 0,
    }
    data = load_playbook_store()
    entries = [e for e in data.get("entries", []) if isinstance(e, dict)]
    entries.append(entry)
    data["entries"] = entries
    _save_playbook_store(data)
    return entry


def delete_playbook_entry(entry_id: str) -> bool:
    data = load_playbook_store()
    entries = [e for e in data.get("entries", []) if isinstance(e, dict) and str(e.get("id")) != entry_id]
    if len(entries) == len(data.get("entries", [])):
        return False
    data["entries"] = entries
    _save_playbook_store(data)
    return True


def export_playbook_bundle() -> dict[str, Any]:
    return {
        "playbook": load_playbook_store(),
        "feedback_tail": _load_feedback_log(),
    }


def _tokenize(text: str) -> set[str]:
    return set(m.group(0).lower() for m in re.finditer(r"[\wÀ-ÿ]{2,}", text, flags=re.UNICODE))


def build_playbook_context_block(*, query: str) -> str | None:
    """
    RAG léxico local: cruza tokens da query com título+corpo+tags; ordena por score
    e por votos úteis. Ignora expirados. Respeita PLAYBOOK_MAX_BLOCK_CHARS.
    """
    if not PLAYBOOK_FEATURE_ENABLED:
        return None
    q = (query or "").strip()
    if len(q) < 2:
        return None
    q_tokens = _tokenize(q)
    if not q_tokens:
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    for e in load_playbook_store().get("entries", []):
        if not isinstance(e, dict) or _is_expired(e):
            continue
        blob = f"{e.get('title','')} {e.get('body','')} {' '.join(e.get('tags') or [])}"
        doc_tokens = _tokenize(str(blob))
        overlap = len(q_tokens & doc_tokens)
        if overlap <= 0:
            continue
        hv = int(e.get("helpful_votes") or 0)
        nh = int(e.get("not_helpful_votes") or 0)
        boost = 1.0 + min(hv, 50) * 0.08 - min(nh, 50) * 0.04
        score = overlap * max(0.25, boost)
        scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    picked = [e for _, e in scored[: max(1, PLAYBOOK_MAX_SNIPPETS_RETRIEVAL)]]
    if not picked:
        return None

    lines: list[str] = [
        "[PLAYBOOK_LOCAL — receitas curadas; não são permissões nem policy; segue PROTOCOLO_AGENT_TOOLS e fila HITL]",
        "",
    ]
    for e in picked:
        eid = str(e.get("id", ""))
        title = str(e.get("title", "")).strip()
        body = str(e.get("body", "")).strip()
        tags = e.get("tags") if isinstance(e.get("tags"), list) else []
        tag_s = ", ".join(str(t) for t in tags[:8])
        lines.append(f"## id={eid}")
        lines.append(f"Título: {title}")
        if tag_s:
            lines.append(f"Tags: {tag_s}")
        lines.append(body)
        lines.append("")
    body = "\n".join(lines).strip()
    if len(body) > PLAYBOOK_MAX_BLOCK_CHARS:
        body = body[: max(0, PLAYBOOK_MAX_BLOCK_CHARS - 20)].rstrip() + "\n… (truncado)"
    return body


def build_playbook_system_message(*, query: str) -> dict[str, str] | None:
    block = build_playbook_context_block(query=query)
    if not block:
        return None
    return {"role": "system", "content": block}


def _load_feedback_log() -> dict[str, Any]:
    path = _feedback_path()
    if not path.is_file():
        return {"version": 1, "events": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "events": []}
    if not isinstance(raw, dict):
        return {"version": 1, "events": []}
    ev = raw.get("events")
    if not isinstance(ev, list):
        return {"version": 1, "events": []}
    return {"version": int(raw.get("version") or 1), "events": ev}


def _append_feedback_event(event: dict[str, Any]) -> None:
    path = _feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_feedback_log()
    events = [e for e in data.get("events", []) if isinstance(e, dict)]
    events.append(event)
    cap = max(10, PLAYBOOK_FEEDBACK_LOG_MAX_EVENTS)
    events = events[-cap:]
    data["events"] = events
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_assistant_feedback(
    *,
    request_id: str,
    vote: Literal["up", "down"],
    playbook_snippet_id: str | None,
) -> dict[str, Any]:
    rid = (request_id or "").strip()
    if len(rid) < 8:
        raise ValueError("request_id_invalid")
    snippet_updated = False
    raw_playbook_snippet_id = playbook_snippet_id
    if playbook_snippet_id:
        if not PLAYBOOK_FEATURE_ENABLED:
            raise ValueError("playbook_disabled")
        elif not CENTRAL_FOCUS_MODE:
            sid = playbook_snippet_id.strip()
            data = load_playbook_store()
            changed = False
            for e in data.get("entries", []):
                if not isinstance(e, dict) or str(e.get("id")) != sid:
                    continue
                if _is_expired(e):
                    raise ValueError("snippet_expired")
                if vote == "up":
                    e["helpful_votes"] = int(e.get("helpful_votes") or 0) + 1
                else:
                    e["not_helpful_votes"] = int(e.get("not_helpful_votes") or 0) + 1
                changed = True
                break
            if not changed:
                raise ValueError("snippet_not_found")
            _save_playbook_store(data)
            snippet_updated = True

    _append_feedback_event(
        {
            "ts": _utcnow().isoformat(),
            "request_id": rid,
            "vote": vote,
            "playbook_snippet_id": raw_playbook_snippet_id,
            "snippet_counters_updated": snippet_updated,
        }
    )
    return {"ok": True, "snippet_counters_updated": snippet_updated}


# ═══════════════════════════════════════════════════════════════════
# PROMOTION CANDIDATES
# ═══════════════════════════════════════════════════════════════════

# Eventos `*_done` de acções com fila HITL / approval_id (exclui fluxos assistant_*).
_ELIGIBLE_AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "p1_process_signal_done",
        "p2_systemd_restart_done",
        "p2_systemd_stop_done",
        "p2_systemd_user_unit_disable_done",
        "p3_systemd_unit_enable_done",
        "p3_systemd_unit_disable_done",
        "p3_os_account_unix_useradd_done",
        "p3_os_power_reboot_done",
        "p3_os_power_shutdown_done",
        "p1_desktop_open_url_done",
        "p1_desktop_notify_done",
        "p1_network_probe_done",
        "p1_read_external_file_done",
        "p2_write_config_file_done",
        "p2_mutate_external_done",
        "p2_firewall_rule_apply_done",
        "p3_firewall_policy_apply_done",
        "p2_os_packages_install_done",
        "p3_os_packages_upgrade_all_done",
    }
)

_BODY_SOFT_MAX = 7800


def _promotion_store_path() -> Path:
    return Path(PLAYBOOK_PROMOTION_CANDIDATES_PATH)


def _empty_promotion_store() -> dict[str, Any]:
    return {"version": 1, "items": []}


def load_promotion_store() -> dict[str, Any]:
    path = _promotion_store_path()
    if not path.is_file():
        return _empty_promotion_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_promotion_store()
    if not isinstance(raw, dict):
        return _empty_promotion_store()
    items = raw.get("items")
    if not isinstance(items, list):
        return _empty_promotion_store()
    return {"version": int(raw.get("version") or 1), "items": items}


def _save_promotion_store(data: dict[str, Any]) -> None:
    path = _promotion_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _build_proposed_content(
    *,
    audit_event: str,
    approval_id: str,
    request_id: str,
    action_id: str,
    approval_payload: dict[str, Any] | None,
    audit_extras: dict[str, Any],
) -> tuple[str, str]:
    title = f"Execução aprovada: {action_id}"[:_TITLE_MAX]
    payload_block = ""
    if approval_payload is not None:
        try:
            raw = json.dumps(approval_payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            raw = repr(approval_payload)
    else:
        raw = "(payload indisponível — registo já não está na fila de aprovações)"
    if len(raw) > 4000:
        raw = raw[:3990] + "\n… (truncado)"
    extras_lines = []
    for k in sorted(audit_extras.keys()):
        if k in ("event", "ts", "source", "result_ok", "approval_id", "request_id", "action_id"):
            continue
        v = audit_extras[k]
        extras_lines.append(f"- **{k}:** `{v}`")
    extras_s = "\n".join(extras_lines) if extras_lines else "- *(sem campos extra no audit)*"

    body = (
        "# Candidato a playbook (revisão humana obrigatória)\n\n"
        "Texto gerado **automaticamente** a partir de dados estruturados (audit + fila). "
        "**Não** inclui resposta do modelo LLM. Edite antes de materializar.\n\n"
        f"- **Evento de audit:** `{audit_event}`\n"
        f"- **request_id:** `{request_id}`\n"
        f"- **approval_id:** `{approval_id}`\n"
        f"- **action_id:** `{action_id}`\n\n"
        "## Campos extra no evento de execução\n\n"
        f"{extras_s}\n\n"
        "## Payload aprovado (registo na fila)\n\n"
        "```json\n"
        f"{raw}\n"
        "```\n"
    )
    if len(body) > _BODY_SOFT_MAX:
        body = body[: _BODY_SOFT_MAX - 40].rstrip() + "\n\n… (corpo truncado — edite na UI)\n"
    return title, body


def maybe_record_from_audit_event(ev: dict[str, Any]) -> None:
    """
    Chamado após `write_event` bem sucedido. Nunca levanta para fora (falhas = log).
    """
    if not PLAYBOOK_FEATURE_ENABLED or not PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED:
        return
    event_name = str(ev.get("event") or "")
    if event_name not in _ELIGIBLE_AUDIT_EVENTS:
        return
    if ev.get("result_ok") is not True:
        return
    approval_id = str(ev.get("approval_id") or "").strip()
    if not approval_id:
        return

    tid = str(ev.get("tenant_id") or "").strip() or resolve_tenant_id_for_store()
    rec = get_approval(approval_id, tenant_id=tid)
    action_id = str(ev.get("action_id") or (rec.get("action_id") if rec else "") or "").strip()
    request_id = str(ev.get("request_id") or (rec.get("request_id") if rec else "") or "").strip()
    approval_payload: dict[str, Any] | None = None
    if rec and isinstance(rec.get("payload"), dict):
        approval_payload = dict(rec["payload"])

    extras = {k: v for k, v in ev.items() if k not in ("approval_id", "request_id", "action_id")}
    proposed_title, proposed_body = _build_proposed_content(
        audit_event=event_name,
        approval_id=approval_id,
        request_id=request_id or "—",
        action_id=action_id or "—",
        approval_payload=approval_payload,
        audit_extras=extras,
    )

    data = load_promotion_store()
    items = [i for i in data.get("items", []) if isinstance(i, dict)]
    for it in items:
        if str(it.get("approval_id")) == approval_id and str(it.get("status")) == "pending":
            return

    entry = {
        "candidate_id": str(uuid.uuid4()),
        "created_at": _utcnow().isoformat(),
        "status": "pending",
        "source_audit_event": event_name,
        "approval_id": approval_id,
        "request_id": request_id,
        "action_id": action_id,
        "proposed_title": proposed_title,
        "proposed_body": proposed_body,
        "materialized_playbook_id": None,
    }
    items.append(entry)
    data["items"] = items
    try:
        _save_promotion_store(data)
    except OSError as exc:
        log.warning("playbook promotion candidates: falha ao gravar %s: %s", _promotion_store_path(), exc)


def list_pending_candidates() -> list[dict[str, Any]]:
    data = load_promotion_store()
    out: list[dict[str, Any]] = []
    for it in data.get("items", []):
        if not isinstance(it, dict):
            continue
        if str(it.get("status")) != "pending":
            continue
        out.append(
            {
                "candidate_id": str(it.get("candidate_id", "")),
                "created_at": str(it.get("created_at", "")),
                "source_audit_event": str(it.get("source_audit_event", "")),
                "approval_id": str(it.get("approval_id", "")),
                "request_id": str(it.get("request_id", "")),
                "action_id": str(it.get("action_id", "")),
                "proposed_title": str(it.get("proposed_title", "")),
                "proposed_body": str(it.get("proposed_body", "")),
            }
        )
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def dismiss_candidate(candidate_id: str) -> dict[str, Any] | None:
    data = load_promotion_store()
    items = [i for i in data.get("items", []) if isinstance(i, dict)]
    found: dict[str, Any] | None = None
    for it in items:
        if str(it.get("candidate_id")) == candidate_id and str(it.get("status")) == "pending":
            it["status"] = "dismissed"
            it["dismissed_at"] = _utcnow().isoformat()
            found = dict(it)
            break
    if found is None:
        return None
    data["items"] = items
    _save_promotion_store(data)
    return found


def materialize_candidate(
    candidate_id: str,
    *,
    title_override: str | None,
    body_override: str | None,
) -> dict[str, Any] | None:
    if not PLAYBOOK_FEATURE_ENABLED:
        raise ValueError("playbook_desligado")
    data = load_promotion_store()
    items = [i for i in data.get("items", []) if isinstance(i, dict)]
    target: dict[str, Any] | None = None
    for it in items:
        if str(it.get("candidate_id")) == candidate_id and str(it.get("status")) == "pending":
            target = it
            break
    if target is None:
        return None

    def _pick(override: str | None, fallback: str) -> str:
        if override is None:
            return fallback.strip()
        s = override.strip()
        return s if s else fallback.strip()

    title = _pick(title_override, str(target.get("proposed_title") or ""))
    body = _pick(body_override, str(target.get("proposed_body") or ""))
    tags = ["promocao-governada"]
    entry = add_playbook_entry_manual(title=title, body=body, tags=tags, ttl_days=None)
    target["status"] = "materialized"
    target["materialized_at"] = _utcnow().isoformat()
    target["materialized_playbook_id"] = entry["id"]
    data["items"] = items
    _save_promotion_store(data)
    return {"candidate": dict(target), "playbook_entry": entry}


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_playbook = APIRouter()


# ── Helpers ──

def _playbook_surface_enabled() -> bool:
    """Playbook exposto na API/UI (desligado em modo produto enxuto)."""
    return bool(PLAYBOOK_FEATURE_ENABLED) and (not CENTRAL_FOCUS_MODE)


def _central_focus_abort() -> None:
    if CENTRAL_FOCUS_MODE:
        raise HTTPException(status_code=404, detail="not_found")


# ── Models ──

class PlaybookCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    ttl_days: int | None = Field(None, ge=1, le=3650)


class PlaybookPromotionMaterializeRequest(BaseModel):
    """Corpo opcional; campos vazios usam título/corpo propostos no candidato."""

    title: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=8000)


class AssistantFeedbackRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=200)
    vote: Literal["up", "down"]
    playbook_snippet_id: str | None = Field(None, max_length=80)


# ── Routes: Playbook CRUD ──

@router_playbook.get("/ui/playbook", tags=["OpsDashboard"])
def ui_playbook_list() -> dict[str, Any]:
    """L3-1: lista metadados de entradas (corpo só em export ou criação)."""
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        return {"feature_enabled": False, "items": []}
    return {"feature_enabled": True, "items": list_playbook_entries_meta()}


@router_playbook.post("/ui/playbook", tags=["OpsDashboard"])
def ui_playbook_create(payload: PlaybookCreateRequest) -> dict[str, Any]:
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    try:
        entry = add_playbook_entry_manual(
            title=payload.title,
            body=payload.body,
            tags=payload.tags,
            ttl_days=payload.ttl_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_orchestrator_audit({"event": "playbook_entry_created", "playbook_id": entry["id"], "title": entry.get("title")})
    return {"entry": entry}


@router_playbook.delete("/ui/playbook/{entry_id}", tags=["OpsDashboard"])
def ui_playbook_delete(entry_id: str) -> dict[str, Any]:
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    if not delete_playbook_entry(entry_id):
        raise HTTPException(status_code=404, detail="not_found")
    write_orchestrator_audit({"event": "playbook_entry_deleted", "playbook_id": entry_id})
    return {"ok": True}


@router_playbook.get("/ui/playbook/export", tags=["OpsDashboard"])
def ui_playbook_export() -> dict[str, Any]:
    """L3-2: export JSON para curadoria (playbook + fila curta de feedback)."""
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    return export_playbook_bundle()


# ── Routes: Promotion Candidates ──

@router_playbook.get("/ui/playbook/promotion-candidates", tags=["OpsDashboard"])
def ui_playbook_promotion_candidates_list() -> dict[str, Any]:
    """NEXT #7: candidatos a playbook após execução aprovada (lista só pendentes)."""
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    if not PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED:
        return {
            "feature_enabled": True,
            "promotion_candidates_enabled": False,
            "items": [],
        }
    return {
        "feature_enabled": True,
        "promotion_candidates_enabled": True,
        "items": list_pending_candidates(),
    }


@router_playbook.post("/ui/playbook/promotion-candidates/{candidate_id}/dismiss", tags=["OpsDashboard"])
def ui_playbook_promotion_candidates_dismiss(candidate_id: str) -> dict[str, Any]:
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    if not PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_promotion_candidates_desligado")
    row = dismiss_candidate(candidate_id)
    if not row:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    write_orchestrator_audit(
        {
            "event": "playbook_promotion_candidate_dismissed",
            "candidate_id": candidate_id,
            "approval_id": row.get("approval_id"),
            "action_id": row.get("action_id"),
        }
    )
    return {"ok": True, "candidate_id": candidate_id}


@router_playbook.post("/ui/playbook/promotion-candidates/{candidate_id}/materialize", tags=["OpsDashboard"])
def ui_playbook_promotion_candidates_materialize(
    candidate_id: str,
    payload: PlaybookPromotionMaterializeRequest = Body(default_factory=PlaybookPromotionMaterializeRequest),
) -> dict[str, Any]:
    """Materializa entrada no playbook (`provenance: manual`) a partir de um candidato."""
    _central_focus_abort()
    if not PLAYBOOK_FEATURE_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_desligado")
    if not PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED:
        raise HTTPException(status_code=503, detail="playbook_promotion_candidates_desligado")
    try:
        out = materialize_candidate(
            candidate_id,
            title_override=payload.title,
            body_override=payload.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not out:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    entry = out["playbook_entry"]
    write_orchestrator_audit(
        {
            "event": "playbook_entry_created",
            "playbook_id": entry["id"],
            "title": entry.get("title"),
            "source": "playbook_promotion_candidate",
            "promotion_candidate_id": candidate_id,
        }
    )
    write_orchestrator_audit(
        {
            "event": "playbook_promotion_materialized",
            "candidate_id": candidate_id,
            "playbook_id": entry["id"],
            "approval_id": out["candidate"].get("approval_id"),
        }
    )
    return {"playbook_entry": entry, "candidate": out["candidate"]}


# ── Routes: Feedback ──

@router_playbook.post("/ui/assistant_feedback", tags=["OpsDashboard"])
def ui_assistant_feedback(payload: AssistantFeedbackRequest) -> dict[str, Any]:
    """L3-2: voto útil / não útil; opcionalmente actualiza contadores de um snippet do playbook."""
    try:
        out = record_assistant_feedback(
            request_id=payload.request_id,
            vote=payload.vote,
            playbook_snippet_id=payload.playbook_snippet_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_orchestrator_audit({"event": "assistant_feedback", "request_id": payload.request_id, "vote": payload.vote})
    return {"ok": True, **(out or {})}
