"""Resolve per-client paths under CENTRAL_ROOT/state/clients/{client_id}/."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import CENTRAL_DEFAULT_CLIENT_ID
from app.shared.tenant_context import get_current_client_id


def _central_root() -> str:
    from app import config as cfg  # noqa: PLC0415

    return (cfg.CENTRAL_ROOT or "").strip()

_CLIENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def sanitize_client_id(raw: str) -> str:
    s = (raw or "").strip()
    if not _CLIENT_ID_RE.fullmatch(s):
        raise ValueError("invalid_client_id")
    return s


def resolve_client_scoped_file(legacy_config_path: str, *, default_filename: str) -> Path:
    """
    When no tenant is active, use the legacy absolute path from config/env.
    When `client_id` is set (JWT), use `CENTRAL_ROOT/state/clients/{client_id}/{basename}`.
    """
    legacy = Path(legacy_config_path or "").expanduser()
    cid = get_current_client_id()
    if not cid:
        return legacy
    safe = sanitize_client_id(cid)
    root = _central_root()
    if not root:
        return legacy
    name = legacy.name or default_filename
    return Path(root) / "state" / "clients" / safe / name


def resolve_preferences_path(legacy_path: str) -> Path:
    return resolve_client_scoped_file(legacy_path, default_filename="assistant_preferences.json")


def resolve_widget_slot_graph_path(legacy_path: str) -> Path:
    return resolve_client_scoped_file(legacy_path, default_filename="widget_slot_graph.json")


def resolve_chat_sessions_path(legacy_path: str) -> Path:
    return resolve_client_scoped_file(legacy_path, default_filename="chat_sessions.json")


def resolve_session_events_path(legacy_path: str) -> Path:
    return resolve_client_scoped_file(legacy_path, default_filename="session_events.jsonl")


def resolve_approvals_store_path(legacy_path: str, *, tenant_id: str) -> Path:
    """Per-tenant approvals JSON under ``state/clients/{tenant_id}/approvals.json``."""
    tid = sanitize_client_id(tenant_id)
    root = _central_root()
    legacy_p = Path(legacy_path or "").expanduser()
    name = legacy_p.name or "approvals.json"
    if root:
        return Path(root) / "state" / "clients" / tid / name
    if tid == sanitize_client_id(CENTRAL_DEFAULT_CLIENT_ID):
        return legacy_p
    return legacy_p.parent / "clients" / tid / name
