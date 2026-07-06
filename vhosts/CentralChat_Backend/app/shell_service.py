"""Shell / terminal tools — approval-gated execution via client connector."""

from __future__ import annotations

import re
from typing import Any

from app.approvals import validate_and_normalize_approval_payload
from app.config import CENTRAL_PRODUCT_MODE
from app.connector import SHELL_EXEC_ACTION_ID
from app.shared.approvals_store import create_pending, resolve_tenant_id_for_store
from app.shared.workspace_context import get_request_workspace_root
from app.shared.workspace_guard import WorkspaceGuardError, resolve_workspace_path

_ELEVATION_RE = re.compile(
    r"\b(sudo|su\s|runuser|pkexec|dbus-send|curl|wget|ssh|scp|nc\s|netcat|telnet)\b",
    re.IGNORECASE,
)


def _workspace_root() -> str | None:
    return get_request_workspace_root()


def propose_terminal_command(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """
    Product-mode terminal: always HITL (P2) → shell.exec job after approve + daemon.
    """
    if not CENTRAL_PRODUCT_MODE:
        return {"ok": False, "error": "product_mode_required", "request_id": request_id}

    command = str(arguments.get("command", "")).strip()
    if not command:
        return {"ok": False, "error": "empty_command", "request_id": request_id}
    if _ELEVATION_RE.search(command):
        return {"ok": False, "error": "elevation_forbidden", "request_id": request_id}

    root = _workspace_root()
    if not root:
        return {
            "ok": False,
            "error": "workspace_not_bound",
            "request_id": request_id,
            "message_pt": "Workspace obrigatório para terminal (X-Central-Workspace ou central workspace).",
        }

    workdir_raw = arguments.get("workdir")
    try:
        if workdir_raw and str(workdir_raw).strip():
            cwd = resolve_workspace_path(workspace_root=root, path=str(workdir_raw))
        else:
            cwd = root
    except WorkspaceGuardError as exc:
        return {"ok": False, "error": exc.code, "request_id": request_id}

    timeout = max(1, min(600, int(arguments.get("timeout", 120))))
    background = bool(arguments.get("background", False))

    raw_payload: dict[str, Any] = {
        "mode": "sh_c",
        "sh_c": command,
        "argv": None,
        "cwd": cwd,
        "shell_session_id": None,
        "intent": command[:512],
        "timeout_sec": timeout,
    }
    store_payload, err = validate_and_normalize_approval_payload(SHELL_EXEC_ACTION_ID, raw_payload)
    if err or store_payload is None:
        return {"ok": False, "error": err or "invalid_payload", "request_id": request_id}

    tid = resolve_tenant_id_for_store()
    rec = create_pending(
        request_id=request_id,
        action_id=SHELL_EXEC_ACTION_ID,
        risk_level="P2",
        payload={
            **store_payload,
            "preview": command,
            "background": background,
        },
        tenant_id=tid,
        requires_double_confirmation=False,
        requires_confirmation=True,
    )
    approval_id = str(rec.get("approval_id") or "")
    return {
        "ok": True,
        "status": "approval_required",
        "approval_id": approval_id,
        "action_id": SHELL_EXEC_ACTION_ID,
        "command": command,
        "cwd": cwd,
        "preview": command,
        "timeout_sec": timeout,
        "background": background,
        "request_id": request_id,
        "message_pt": (
            f"Comando pendente de aprovação. Use: central diff {approval_id[:8]} "
            f"e central approve {approval_id[:8]}"
        ),
    }
