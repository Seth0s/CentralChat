"""D2.2 — Request-scoped log context (session_id, approval_id)."""

from __future__ import annotations

import contextvars

_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("log_session_id", default=None)
_approval_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("log_approval_id", default=None)


def set_log_context(*, session_id: str | None = None, approval_id: str | None = None) -> None:
    if session_id is not None:
        _session_id.set(session_id)
    if approval_id is not None:
        _approval_id.set(approval_id)


def get_log_session_id() -> str | None:
    return _session_id.get()


def get_log_approval_id() -> str | None:
    return _approval_id.get()


def clear_log_context() -> None:
    _session_id.set(None)
    _approval_id.set(None)
