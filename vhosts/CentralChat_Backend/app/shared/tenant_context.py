"""Request-scoped tenant (`client_id`) for multi-tenant L4 paths (Fase 4)."""

from __future__ import annotations

from contextvars import ContextVar

_current_client_id: ContextVar[str | None] = ContextVar("current_client_id", default=None)
_current_sub: ContextVar[str | None] = ContextVar("current_sub", default=None)


def set_tenant_context(*, client_id: str | None, sub: str | None = None) -> None:
    _current_client_id.set(client_id)
    _current_sub.set(sub)


def get_current_client_id() -> str | None:
    return _current_client_id.get()


def get_current_sub() -> str | None:
    return _current_sub.get()
