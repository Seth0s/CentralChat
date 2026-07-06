"""Regras de identificação e título de sessão de chat (contrato §11)."""

from __future__ import annotations

MIN_SESSION_ID_LEN = 8
TITLE_MAX_LEN = 120


def normalize_session_title(raw: str | None, *, default: str = "Nova conversa") -> str:
    t = (raw or "").strip() or default
    return t[:TITLE_MAX_LEN] if len(t) > TITLE_MAX_LEN else t


def truncate_title(raw: str) -> str:
    """Título após trim, truncado a TITLE_MAX_LEN (rename PATCH)."""
    s = (raw or "").strip()
    return s[:TITLE_MAX_LEN] if len(s) > TITLE_MAX_LEN else s


def is_valid_session_id(session_id: str | None) -> bool:
    s = (session_id or "").strip()
    return len(s) >= MIN_SESSION_ID_LEN
