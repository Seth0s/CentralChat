"""File change tools — workspace reads, approval-gated writes, connector jobs."""

from __future__ import annotations

import os
import time
from typing import Any

from app.config import CENTRAL_PRODUCT_MODE
from app.connector import (
    FILE_READ_ACTION_ID,
    build_read_payload,
    client_jobs_db_enabled,
    connector_online_for_tenant,
    create_job,
    enqueue_client_file_job,
    find_job_by_approval_id,
    get_job,
    tenant_shell_uses_client_connector,
)
from app.shared.approvals_store import create_pending, resolve_tenant_id_for_store
from app.shared.diff_builder import build_unified_diff, diff_summary
from app.shared.workspace_context import get_request_workspace_root
from app.shared.workspace_guard import WorkspaceGuardError, resolve_workspace_path

FILE_WRITE_ACTION_ID = "file.write"
FILE_PATCH_ACTION_ID = "file.patch"


def _workspace_root() -> str | None:
    return get_request_workspace_root()


def _read_local(path: str, *, offset: int, limit: int, request_id: str) -> dict[str, Any]:
    root = _workspace_root()
    if not root:
        return {
            "ok": False,
            "error": "workspace_not_bound",
            "request_id": request_id,
            "message_pt": "Define workspace: header X-Central-Workspace ou POST /ui/workspace",
        }
    try:
        resolved = resolve_workspace_path(workspace_root=root, path=path)
    except WorkspaceGuardError as exc:
        return {"ok": False, "error": exc.code, "request_id": request_id}
    if not os.path.isfile(resolved):
        return {"ok": False, "error": "not_found", "path": resolved, "request_id": request_id}
    try:
        with open(resolved, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(start + limit, total)
        content = "".join(lines[start:end])
        return {
            "ok": True,
            "path": resolved,
            "total_lines": total,
            "offset": offset,
            "limit": limit,
            "content": content[:100_000],
            "request_id": request_id,
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:500], "path": resolved, "request_id": request_id}


def wait_for_job_result(*, tenant_id: str, job_id: str, timeout_sec: float = 45.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        job = get_job(tenant_id=tenant_id, job_id=job_id)
        if not job:
            return {"ok": False, "error": "job_not_found", "job_id": job_id}
        status = str(job.get("status") or "")
        if status == "succeeded":
            result = job.get("result")
            if isinstance(result, dict):
                return {**result, "ok": result.get("ok", True), "job_id": job_id}
            return {"ok": True, "job_id": job_id, "result": result}
        if status == "failed":
            return {
                "ok": False,
                "error": job.get("error_code") or "job_failed",
                "job_id": job_id,
                "result": job.get("result"),
            }
        time.sleep(0.25)
    return {"ok": False, "error": "job_timeout", "job_id": job_id}


def read_file_for_tool(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    path = str(arguments.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    offset = max(1, int(arguments.get("offset", 1)))
    limit = max(1, min(2000, int(arguments.get("limit", 500))))

    tid = resolve_tenant_id_for_store()
    use_connector = (
        tenant_shell_uses_client_connector()
        and client_jobs_db_enabled()
        and connector_online_for_tenant(tenant_id=tid)
    )
    if use_connector:
        root = _workspace_root()
        if root:
            try:
                path = resolve_workspace_path(workspace_root=root, path=path)
            except WorkspaceGuardError as exc:
                return {"ok": False, "error": exc.code, "request_id": request_id}
        body, verr = build_read_payload({"path": path, "max_bytes": limit * 400})
        if verr or not body:
            return {"ok": False, "error": verr or "invalid_arguments", "request_id": request_id}
        job = enqueue_client_file_job(
            tenant_id=tid,
            action_id=FILE_READ_ACTION_ID,
            payload=body,
            request_id=request_id,
            tool_name="read_file",
        )
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return {"ok": False, "error": "job_enqueue_failed", "request_id": request_id}
        out = wait_for_job_result(tenant_id=tid, job_id=job_id)
        out["request_id"] = request_id
        return out

    return _read_local(path, offset=offset, limit=limit, request_id=request_id)


def _propose_file_change(
    *,
    action_id: str,
    path: str,
    new_content: str,
    request_id: str,
    change_kind: str,
) -> dict[str, Any]:
    root = _workspace_root()
    if not root:
        return {
            "ok": False,
            "error": "workspace_not_bound",
            "request_id": request_id,
            "message_pt": "Workspace obrigatório para escrita (X-Central-Workspace ou central workspace).",
        }
    try:
        resolved = resolve_workspace_path(workspace_root=root, path=path)
    except WorkspaceGuardError as exc:
        return {"ok": False, "error": exc.code, "request_id": request_id}

    old_content = ""
    if os.path.isfile(resolved):
        try:
            with open(resolved, encoding="utf-8", errors="replace") as fh:
                old_content = fh.read()
        except OSError as exc:
            return {"ok": False, "error": str(exc)[:500], "request_id": request_id}

    diff_text = build_unified_diff(path=resolved, old_content=old_content, new_content=new_content)
    summary = diff_summary(diff_text)
    tid = resolve_tenant_id_for_store()
    from app.shared.policy_engine import requires_dual_approval
    from app.shared.tenant_context import get_current_sub

    dual = requires_dual_approval(resolved, tenant_id=tid)
    payload: dict[str, Any] = {
        "path": resolved,
        "new_content": new_content,
        "diff": diff_text,
        "summary": summary,
        "change_kind": change_kind,
    }
    rec = create_pending(
        request_id=request_id,
        action_id=action_id,
        risk_level="P1",
        payload=payload,
        tenant_id=tid,
        requires_double_confirmation=dual,
        requires_confirmation=True,
        requested_by_sub=get_current_sub(),
    )
    approval_id = str(rec.get("approval_id") or "")
    return {
        "ok": True,
        "status": "approval_required",
        "approval_id": approval_id,
        "action_id": action_id,
        "path": resolved,
        "diff": diff_text,
        "summary": summary,
        "request_id": request_id,
        "message_pt": f"Alteração pendente de aprovação ({summary}). Use: central diff {approval_id[:8]}",
    }


def propose_write_file(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not CENTRAL_PRODUCT_MODE:
        return {"ok": False, "error": "product_mode_required", "request_id": request_id}
    path = str(arguments.get("path", "")).strip()
    content = str(arguments.get("content", ""))
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    return _propose_file_change(
        action_id=FILE_WRITE_ACTION_ID,
        path=path,
        new_content=content,
        request_id=request_id,
        change_kind="write",
    )


def propose_patch_file(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not CENTRAL_PRODUCT_MODE:
        return {"ok": False, "error": "product_mode_required", "request_id": request_id}
    path = str(arguments.get("path", "")).strip()
    old_string = str(arguments.get("old_string", ""))
    new_string = str(arguments.get("new_string", ""))
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    if not old_string:
        return {"ok": False, "error": "empty_old_string", "request_id": request_id}

    root = _workspace_root()
    if not root:
        return {"ok": False, "error": "workspace_not_bound", "request_id": request_id}
    try:
        resolved = resolve_workspace_path(workspace_root=root, path=path)
    except WorkspaceGuardError as exc:
        return {"ok": False, "error": exc.code, "request_id": request_id}
    if not os.path.isfile(resolved):
        return {"ok": False, "error": "not_found", "path": resolved, "request_id": request_id}
    try:
        with open(resolved, encoding="utf-8", errors="replace") as fh:
            original = fh.read()
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:500], "request_id": request_id}
    if old_string not in original:
        return {"ok": False, "error": "old_string_not_found", "path": resolved, "request_id": request_id}
    new_content = original.replace(old_string, new_string)
    return _propose_file_change(
        action_id=FILE_PATCH_ACTION_ID,
        path=resolved,
        new_content=new_content,
        request_id=request_id,
        change_kind="patch",
    )


def enqueue_file_job_after_approval(rec: dict[str, Any]) -> dict[str, Any] | None:
    if rec.get("status") != "approved":
        return None
    action_id = str(rec.get("action_id") or "")
    if action_id not in (FILE_WRITE_ACTION_ID, FILE_PATCH_ACTION_ID):
        return None
    if not tenant_shell_uses_client_connector() or not client_jobs_db_enabled():
        return None
    body = rec.get("payload")
    if not isinstance(body, dict):
        return None
    tid = resolve_tenant_id_for_store(str(rec.get("tenant_id") or ""))
    approval_id = str(rec.get("approval_id") or "")
    existing = find_job_by_approval_id(tenant_id=tid, approval_id=approval_id)
    if existing:
        return existing
    path = str(body.get("path") or "")
    new_content = str(body.get("new_content", ""))
    if not path:
        return None
    root = get_request_workspace_root()
    if root:
        try:
            path = resolve_workspace_path(workspace_root=root, path=path)
        except WorkspaceGuardError:
            return None
    return create_job(
        tenant_id=tid,
        action_id=action_id,
        payload={"path": path, "content": new_content},
        approval_id=approval_id,
        tool_call_id=f"file-{approval_id[:8]}",
        session_id=str(rec.get("session_id") or "") or None,
    )
