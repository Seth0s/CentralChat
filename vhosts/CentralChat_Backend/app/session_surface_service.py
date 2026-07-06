"""Session surface state — phase FSM, clarify interrupts, TUI reconnect snapshot."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import CENTRAL_ROOT
from app.domain.chat_sessions_domain import is_valid_session_id
from app.sessions import get_session
from app.shared.pg_tenant import resolve_pg_tenant_id

logger = logging.getLogger(__name__)

VALID_PHASES = frozenset({"idle", "streaming", "waiting_clarify", "waiting_approval"})


def _store_path() -> Path:
    root = (CENTRAL_ROOT or "/tmp/central").strip()
    return Path(root) / "state" / "session_surface.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("session_surface read failed", exc_info=True)
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    Path(tmp).replace(path)


def _entry_key(*, tenant_id: str | None = None, session_id: str) -> str:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    return f"{tid}:{session_id.strip()}"


def _get_entry(session_id: str, *, tenant_id: str | None = None) -> dict[str, Any]:
    key = _entry_key(tenant_id=tenant_id, session_id=session_id)
    rec = _load().get(key)
    return dict(rec) if isinstance(rec, dict) else {}


def _put_entry(session_id: str, entry: dict[str, Any], *, tenant_id: str | None = None) -> None:
    key = _entry_key(tenant_id=tenant_id, session_id=session_id)
    data = _load()
    data[key] = entry
    _save(data)


def get_session_phase(session_id: str, *, tenant_id: str | None = None) -> str:
    if not is_valid_session_id(session_id):
        return "idle"
    phase = str(_get_entry(session_id, tenant_id=tenant_id).get("session_phase") or "idle")
    return phase if phase in VALID_PHASES else "idle"


def set_session_phase(session_id: str, phase: str, *, tenant_id: str | None = None) -> None:
    if not is_valid_session_id(session_id):
        return
    ph = phase if phase in VALID_PHASES else "idle"
    entry = _get_entry(session_id, tenant_id=tenant_id)
    entry["session_phase"] = ph
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    _put_entry(session_id, entry, tenant_id=tenant_id)


def register_clarify_interrupt(
    *,
    session_id: str,
    question: str,
    choices: list[str],
    request_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    interrupt_id = str(uuid.uuid4())
    entry = _get_entry(session_id, tenant_id=tenant_id)
    entry["session_phase"] = "waiting_clarify"
    entry["interrupt"] = {
        "interrupt_id": interrupt_id,
        "kind": "clarify",
        "question": question[:2000],
        "choices": [str(c)[:500] for c in choices[:4]],
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entry["updated_at"] = entry["interrupt"]["created_at"]
    _put_entry(session_id, entry, tenant_id=tenant_id)
    return {"interrupt_id": interrupt_id, **entry["interrupt"]}


def register_pending_approval(
    *,
    session_id: str,
    approval_id: str,
    summary: str,
    tenant_id: str | None = None,
) -> None:
    if not is_valid_session_id(session_id):
        return
    entry = _get_entry(session_id, tenant_id=tenant_id)
    entry["session_phase"] = "waiting_approval"
    entry["pending_approval"] = {
        "approval_id": approval_id,
        "summary": summary[:500],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    entry["updated_at"] = entry["pending_approval"]["updated_at"]
    _put_entry(session_id, entry, tenant_id=tenant_id)


def clear_interrupt(session_id: str, *, tenant_id: str | None = None) -> None:
    entry = _get_entry(session_id, tenant_id=tenant_id)
    entry.pop("interrupt", None)
    if entry.get("session_phase") == "waiting_clarify":
        entry["session_phase"] = "idle"
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    _put_entry(session_id, entry, tenant_id=tenant_id)


def clear_pending_approval(session_id: str, *, tenant_id: str | None = None) -> None:
    entry = _get_entry(session_id, tenant_id=tenant_id)
    entry.pop("pending_approval", None)
    if entry.get("session_phase") == "waiting_approval":
        entry["session_phase"] = "idle"
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    _put_entry(session_id, entry, tenant_id=tenant_id)


def clear_pending_approval_by_approval_id(
    approval_id: str,
    *,
    tenant_id: str | None = None,
) -> None:
    """Clear surface waiting_approval when an approval is resolved out-of-band."""
    aid = (approval_id or "").strip()
    if not aid:
        return
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    data = _load()
    changed = False
    for key, rec in list(data.items()):
        if not isinstance(rec, dict) or not key.startswith(f"{tid}:"):
            continue
        pending = rec.get("pending_approval")
        if not isinstance(pending, dict):
            continue
        if str(pending.get("approval_id") or "") != aid:
            continue
        rec.pop("pending_approval", None)
        if rec.get("session_phase") == "waiting_approval":
            rec["session_phase"] = "idle"
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[key] = rec
        changed = True
    if changed:
        _save(data)


def consume_clarify_response(
    session_id: str,
    *,
    interrupt_id: str,
    choice: str | None,
    custom: str | None,
    tenant_id: str | None = None,
) -> str:
    entry = _get_entry(session_id, tenant_id=tenant_id)
    interrupt = entry.get("interrupt")
    if not isinstance(interrupt, dict):
        raise ValueError("no_active_interrupt")
    if str(interrupt.get("interrupt_id") or "") != interrupt_id.strip():
        raise ValueError("interrupt_mismatch")
    answer = (custom or "").strip() or (choice or "").strip()
    if not answer:
        raise ValueError("empty_response")
    clear_interrupt(session_id, tenant_id=tenant_id)
    set_session_phase(session_id, "streaming", tenant_id=tenant_id)
    return answer


def respond_interrupt_http(
    session_id: str,
    interrupt_id: str,
    *,
    choice: str | None,
    custom: str | None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    if not is_valid_session_id(session_id):
        raise ValueError("invalid_session_id")
    if not get_session(session_id):
        raise ValueError("session_not_found")
    text = consume_clarify_response(
        session_id,
        interrupt_id=interrupt_id,
        choice=choice,
        custom=custom,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "response_text": text,
        "session_phase": get_session_phase(session_id, tenant_id=tenant_id),
    }


def build_surface_snapshot(session_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    if not is_valid_session_id(session_id):
        return None
    session = get_session(session_id)
    if not session:
        return None
    entry = _get_entry(session_id, tenant_id=tenant_id)
    messages = session.get("messages")
    if not isinstance(messages, list):
        messages = []
    return {
        "session_id": session_id,
        "title": session.get("title"),
        "session_phase": entry.get("session_phase") or "idle",
        "messages": messages[-40:],
        "interrupt": entry.get("interrupt"),
        "pending_approval": entry.get("pending_approval"),
        "updated_at": entry.get("updated_at"),
    }
