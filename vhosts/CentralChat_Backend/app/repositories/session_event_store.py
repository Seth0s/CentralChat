"""Append-only session event log (JSONL per tenant, Phase 2)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.context import SessionEvent, SessionEventType
from app.shared.tenant_paths import resolve_session_events_path

_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _events_path() -> Path:
    from app.config import CHAT_SESSIONS_EVENT_LOG_PATH

    return resolve_session_events_path(CHAT_SESSIONS_EVENT_LOG_PATH)


def _meta_path() -> Path:
    return _events_path().with_suffix(".meta.json")


class SessionEventStore:
    """L4 store: one JSONL file per tenant scope (see ``tenant_paths``)."""

    def append(self, event: SessionEvent) -> SessionEvent:
        row = event.model_dump(mode="json", by_alias=True)
        if not row.get("event_id"):
            row["event_id"] = str(uuid.uuid4())
            event = event.model_copy(update={"event_id": row["event_id"]})
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            path = _events_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return event

    def append_turn(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
        ts: datetime | None = None,
        slot: int | None = None,
    ) -> tuple[SessionEvent, SessionEvent]:
        base = ts or _utc_now()
        user_payload: dict[str, Any] = {"content": (user_text or "").strip()}
        asst_payload: dict[str, Any] = {"content": assistant_text or ""}
        if slot is not None and 1 <= int(slot) <= 4:
            user_payload["slot"] = int(slot)
            asst_payload["slot"] = int(slot)
        user_ev = SessionEvent(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=SessionEventType.USER_MESSAGE,
            payload=user_payload,
            ts=base,
            event_id=str(uuid.uuid4()),
        )
        asst_ev = SessionEvent(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            payload=asst_payload,
            ts=base + timedelta(microseconds=1),
            event_id=str(uuid.uuid4()),
        )
        return self.append(user_ev), self.append(asst_ev)

    def list_for_session(self, tenant_id: str, session_id: str) -> list[SessionEvent]:
        sid = (session_id or "").strip()
        if len(sid) < 8:
            return []
        out: list[SessionEvent] = []
        for ev in self.iter_all(tenant_id=tenant_id):
            if ev.session_id == sid:
                out.append(ev)
        return out

    def session_ids_with_events(self, tenant_id: str) -> set[str]:
        return {ev.session_id for ev in self.iter_all(tenant_id=tenant_id)}

    def iter_all(self, *, tenant_id: str) -> list[SessionEvent]:
        tid = (tenant_id or "").strip()
        path = _events_path()
        if not path.is_file():
            return []
        events: list[SessionEvent] = []
        with _lock:
            text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("tenant_id") or "") != tid:
                    continue
                events.append(SessionEvent.model_validate(raw))
            except Exception:
                continue
        return events

    def delete_session(self, tenant_id: str, session_id: str) -> int:
        """Rewrite JSONL without events for ``session_id``; returns rows removed."""
        sid = (session_id or "").strip()
        tid = (tenant_id or "").strip()
        path = _events_path()
        if not path.is_file():
            return 0
        with _lock:
            kept: list[str] = []
            removed = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s:
                    continue
                try:
                    raw = json.loads(s)
                    if (
                        isinstance(raw, dict)
                        and str(raw.get("tenant_id") or "") == tid
                        and str(raw.get("session_id") or "") == sid
                    ):
                        removed += 1
                        continue
                except Exception:
                    pass
                kept.append(s)
            if removed:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
                tmp.replace(path)
        return removed

    def load_migration_meta(self) -> dict[str, Any]:
        path = _meta_path()
        if not path.is_file():
            return {"schema": 1, "migrated_session_ids": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ids = data.get("migrated_session_ids")
                if isinstance(ids, list):
                    return {"schema": 1, "migrated_session_ids": [str(x) for x in ids]}
        except Exception:
            pass
        return {"schema": 1, "migrated_session_ids": []}

    def save_migration_meta(self, meta: dict[str, Any]) -> None:
        path = _meta_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
