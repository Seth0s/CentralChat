"""Request-scoped workspace root (from header or persisted binding)."""

from __future__ import annotations

from contextvars import ContextVar

_workspace_root: ContextVar[str | None] = ContextVar("central_workspace_root", default=None)


def set_request_workspace_root(path: str | None) -> None:
    _workspace_root.set((path or "").strip() or None)


def get_request_workspace_root() -> str | None:
    return _workspace_root.get()
