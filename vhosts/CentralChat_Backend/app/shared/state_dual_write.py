"""T9 — State → Postgres: dual-write wrapper + data migration.

Wraps existing disk-based stores with optional Postgres writes.
When CENTRAL_STATE_PG_ENABLED=1, writes go to both disk and PG.
Reads prioritize PG, with fallback to disk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import MEMORY_DB_URL, MEMORY_ENABLED
from app.shared.pg_tenant import memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# Opt-in via env: CENTRAL_STATE_PG_ENABLED=1
_STATE_PG_ENABLED = (
    __import__("os").getenv("CENTRAL_STATE_PG_ENABLED", "0").strip().lower()
    in ("1", "true", "yes")
)


def _pg_available() -> bool:
    return _STATE_PG_ENABLED and memory_db_enabled()


def _get_pg_conn():
    import psycopg

    return psycopg.connect(MEMORY_DB_URL, autocommit=True)


def _ensure_tables(cur: Any) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS session_events (
            id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'default',
            session_id TEXT NOT NULL, event_type TEXT NOT NULL,
            payload JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now());"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'default',
            title TEXT DEFAULT 'Conversa', pinned BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id BIGSERIAL PRIMARY KEY, session_id TEXT REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL, content TEXT NOT NULL, slot INT,
            created_at TIMESTAMPTZ DEFAULT now());"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS assistant_preferences (
            tenant_id TEXT PRIMARY KEY, prefs_json JSONB DEFAULT '{}',
            updated_at TIMESTAMPTZ DEFAULT now());"""
    )


# ═══════════════════════════════════════════════════════════════════
# DUAL-WRITE: Session Events
# ═══════════════════════════════════════════════════════════════════


def pg_write_session_event(
    tenant_id: str,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort PG write alongside disk event log."""
    if not _pg_available():
        return
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute(
            """INSERT INTO session_events (tenant_id, session_id, event_type, payload)
               VALUES (%s, %s, %s, %s);""",
            (tenant_id, session_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )
        conn.close()
    except Exception as exc:
        logger.debug("pg_write_session_event failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# DUAL-WRITE: Chat Sessions
# ═══════════════════════════════════════════════════════════════════


def pg_write_chat_session(
    tenant_id: str,
    session_id: str,
    *,
    title: str = "Conversa",
    pinned: bool = False,
) -> None:
    if not _pg_available():
        return
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute(
            """INSERT INTO chat_sessions (id, tenant_id, title, pinned)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
               title = EXCLUDED.title, pinned = EXCLUDED.pinned, updated_at = now();""",
            (session_id, tenant_id, title, pinned),
        )
        conn.close()
    except Exception as exc:
        logger.debug("pg_write_chat_session failed: %s", exc)


def pg_append_chat_message(
    session_id: str,
    *,
    role: str,
    content: str,
    slot: int | None = None,
) -> None:
    if not _pg_available():
        return
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute(
            """INSERT INTO chat_messages (session_id, role, content, slot)
               VALUES (%s, %s, %s, %s);""",
            (session_id, role, content, slot),
        )
        conn.close()
    except Exception as exc:
        logger.debug("pg_append_chat_message failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# DUAL-WRITE: Preferences
# ═══════════════════════════════════════════════════════════════════


def pg_write_preferences(tenant_id: str, prefs: dict[str, Any]) -> None:
    if not _pg_available():
        return
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute(
            """INSERT INTO assistant_preferences (tenant_id, prefs_json)
               VALUES (%s, %s::jsonb)
               ON CONFLICT (tenant_id) DO UPDATE SET
               prefs_json = EXCLUDED.prefs_json, updated_at = now();""",
            (tenant_id, json.dumps(prefs, ensure_ascii=False)),
        )
        conn.close()
    except Exception as exc:
        logger.debug("pg_write_preferences failed: %s", exc)


def pg_read_preferences(tenant_id: str) -> dict[str, Any] | None:
    """Read preferences from PG (for dual-read pattern)."""
    if not _pg_available():
        return None
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute(
            "SELECT prefs_json FROM assistant_preferences WHERE tenant_id = %s;",
            (tenant_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row and isinstance(row[0], dict):
            return row[0]
        return None
    except Exception:
        return None
