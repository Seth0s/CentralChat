"""H1 — RBAC helpers (roles from JWT claim)."""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import HTTPException

from app.shared.tenant_context import get_current_sub

_current_role: ContextVar[str | None] = ContextVar("current_role", default=None)

VALID_ROLES = frozenset({"viewer", "developer", "reviewer", "lead", "approver", "admin", "auditor"})

ROLE_RANK = {
    "viewer": 1,
    "developer": 2,
    "reviewer": 3,
    "approver": 3,
    "auditor": 3,
    "lead": 4,
    "admin": 4,
}


def set_current_role(role: str | None) -> None:
    r = (role or "").strip().lower() or None
    if r and r not in VALID_ROLES:
        r = "developer"
    _current_role.set(r)


def get_current_role() -> str:
    r = _current_role.get()
    if r and r in VALID_ROLES:
        return r
    return "developer"


def require_any_role(*roles: str) -> None:
    """Raise 403 if current role not in allowed set. Dev mode (no sub) passes."""
    if not get_current_sub():
        return
    cur = get_current_role()
    if cur == "admin":
        return
    allowed = {str(x).strip().lower() for x in roles}
    if cur not in allowed:
        raise HTTPException(status_code=403, detail="insufficient_role")
