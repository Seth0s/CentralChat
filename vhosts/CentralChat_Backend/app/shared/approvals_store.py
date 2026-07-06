"""Approvals queue (HITL). Per-tenant JSON under state/clients/{tenant_id}/ (ADR-017)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.config import APPROVALS_STORE_PATH, CENTRAL_DEFAULT_CLIENT_ID
from app.shared.tenant_context import get_current_client_id
from app.shared.tenant_paths import resolve_approvals_store_path, sanitize_client_id

Status = Literal["pending", "awaiting_double_confirm", "approved", "denied"]


@dataclass(frozen=True)
class ApprovalMutation:
    """Result of approve/deny/confirm-double — supports idempotent replay (B1.5)."""

    record: dict[str, Any]
    changed: bool
    conflict: bool = False

    def __getitem__(self, key: str) -> Any:
        return self.record[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.record.get(key, default)


def resolve_tenant_id_for_store(explicit: str | None = None) -> str:
    """Tenant key for approvals persistence (JWT context or default in dev)."""
    if explicit is not None and str(explicit).strip():
        return sanitize_client_id(str(explicit).strip())
    cid = get_current_client_id()
    if cid:
        return sanitize_client_id(cid)
    return sanitize_client_id(CENTRAL_DEFAULT_CLIENT_ID)


def _store_path(tenant_id: str) -> Path:
    tid = resolve_tenant_id_for_store(tenant_id)
    legacy = (APPROVALS_STORE_PATH or "").strip() or "/tmp/central_approvals.json"
    return resolve_approvals_store_path(legacy, tenant_id=tid)


def _load_all(*, tenant_id: str) -> list[dict[str, Any]]:
    path = _store_path(tenant_id)
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    return []


def _save_all(items: list[dict[str, Any]], *, tenant_id: str) -> None:
    path = _store_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def create_pending(
    request_id: str,
    action_id: str,
    risk_level: str,
    payload: dict[str, Any],
    expires_at: str | None = None,
    *,
    tenant_id: str,
    requires_double_confirmation: bool = False,
    requires_confirmation: bool = True,
    session_id: str | None = None,
    requested_by_sub: str | None = None,
) -> dict[str, Any]:
    tid = resolve_tenant_id_for_store(tenant_id)
    approval_id = str(uuid.uuid4())
    rec: dict[str, Any] = {
        "approval_id": approval_id,
        "tenant_id": tid,
        "request_id": request_id,
        "action_id": action_id,
        "risk_level": risk_level,
        "payload": payload,
        "status": "pending",
        "requires_double_confirmation": bool(requires_double_confirmation),
        "requires_confirmation": bool(requires_confirmation),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
    }
    sid = (session_id or "").strip()
    if len(sid) >= 8:
        rec["session_id"] = sid
    req = (requested_by_sub or "").strip()
    if req:
        rec["requested_by_sub"] = req
    items = _load_all(tenant_id=tid)
    items.append(rec)
    _save_all(items, tenant_id=tid)
    return rec


def list_approvals(status: str | None = None, *, tenant_id: str) -> list[dict[str, Any]]:
    tid = resolve_tenant_id_for_store(tenant_id)
    items = _load_all(tenant_id=tid)
    if status == "pending":
        return [
            x
            for x in items
            if x.get("status") in ("pending", "awaiting_double_confirm")
        ]
    if status:
        return [x for x in items if x.get("status") == status]
    return list(items)


def get_approval(approval_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = resolve_tenant_id_for_store(tenant_id)
    for rec in _load_all(tenant_id=tid):
        if rec.get("approval_id") == approval_id:
            return rec
    return None


def _parse_expires_at(rec: dict[str, Any]) -> datetime | None:
    raw = rec.get("expires_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def approval_is_expired(rec: dict[str, Any]) -> bool:
    exp = _parse_expires_at(rec)
    if exp is None:
        return False
    now = datetime.now(timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return now > exp


def _expire_if_needed(rec: dict[str, Any], *, tenant_id: str, items: list[dict[str, Any]], index: int) -> ApprovalMutation | None:
    if not approval_is_expired(rec):
        return None
    if rec.get("status") not in ("pending", "awaiting_double_confirm"):
        return None
    now = datetime.now(timezone.utc).isoformat()
    rec["status"] = "denied"
    rec["resolved_at"] = now
    rec["deny_reason"] = "expired"
    items[index] = rec
    _save_all(items, tenant_id=tenant_id)
    return ApprovalMutation(record=rec, changed=True)


def set_execution_status(
    approval_id: str,
    *,
    tenant_id: str,
    execution_status: str,
    job_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any] | None:
    """Link client job outcome back to approval record (B1.4)."""
    tid = resolve_tenant_id_for_store(tenant_id)
    items = _load_all(tenant_id=tid)
    now = datetime.now(timezone.utc).isoformat()
    for i, rec in enumerate(items):
        if rec.get("approval_id") != approval_id:
            continue
        if rec.get("status") != "approved":
            return rec
        rec["execution_status"] = execution_status
        rec["executed_at"] = now
        if job_id:
            rec["client_job_id"] = job_id
        if error_code:
            rec["execution_error"] = error_code
        items[i] = rec
        _save_all(items, tenant_id=tid)
        return rec
    return None


def approve_or_first_double_step(
    approval_id: str,
    *,
    tenant_id: str,
    approver_sub: str | None = None,
) -> ApprovalMutation | None:
    """
    pending -> approved (sem dupla) ou awaiting_double_confirm (com dupla).
    Idempotent when already approved or awaiting first double step (B1.5).
    """
    tid = resolve_tenant_id_for_store(tenant_id)
    items = _load_all(tenant_id=tid)
    now = datetime.now(timezone.utc).isoformat()
    for i, rec in enumerate(items):
        if rec.get("approval_id") != approval_id:
            continue
        status = rec.get("status")
        expired = _expire_if_needed(rec, tenant_id=tid, items=items, index=i)
        if expired is not None:
            return expired
        if status == "pending":
            if rec.get("requires_double_confirmation"):
                rec["status"] = "awaiting_double_confirm"
                rec["first_confirmed_at"] = now
                if approver_sub:
                    rec["first_approver_sub"] = approver_sub.strip()
            else:
                rec["status"] = "approved"
                rec["resolved_at"] = now
            items[i] = rec
            _save_all(items, tenant_id=tid)
            return ApprovalMutation(record=rec, changed=True)
        if status == "awaiting_double_confirm":
            return ApprovalMutation(record=rec, changed=False)
        if status == "approved":
            return ApprovalMutation(record=rec, changed=False)
        if status == "denied":
            return ApprovalMutation(record=rec, changed=False, conflict=True)
        return None
    return None


def confirm_double(
    approval_id: str,
    *,
    tenant_id: str,
    approver_sub: str | None = None,
) -> ApprovalMutation | None:
    """awaiting_double_confirm -> approved; idempotent when already approved (B1.5)."""
    tid = resolve_tenant_id_for_store(tenant_id)
    items = _load_all(tenant_id=tid)
    now = datetime.now(timezone.utc).isoformat()
    for i, rec in enumerate(items):
        if rec.get("approval_id") != approval_id:
            continue
        status = rec.get("status")
        if status == "awaiting_double_confirm":
            first = str(rec.get("first_approver_sub") or "").strip()
            cur = (approver_sub or "").strip()
            if first and cur and first == cur:
                return ApprovalMutation(record=rec, changed=False, conflict=True)
            rec["status"] = "approved"
            rec["second_confirmed_at"] = now
            if cur:
                rec["second_approver_sub"] = cur
            rec["resolved_at"] = now
            items[i] = rec
            _save_all(items, tenant_id=tid)
            return ApprovalMutation(record=rec, changed=True)
        if status == "approved":
            return ApprovalMutation(record=rec, changed=False)
        if status == "denied":
            return ApprovalMutation(record=rec, changed=False, conflict=True)
        if status == "pending":
            return ApprovalMutation(record=rec, changed=False, conflict=True)
        return None
    return None


def set_denied(
    approval_id: str,
    *,
    tenant_id: str,
    reason: str | None = None,
) -> ApprovalMutation | None:
    """Negar a partir de pending ou awaiting_double_confirm; idempotent when denied (B1.5)."""
    tid = resolve_tenant_id_for_store(tenant_id)
    items = _load_all(tenant_id=tid)
    now = datetime.now(timezone.utc).isoformat()
    reason_stripped = (reason or "").strip()
    for i, rec in enumerate(items):
        if rec.get("approval_id") != approval_id:
            continue
        expired = _expire_if_needed(rec, tenant_id=tid, items=items, index=i)
        if expired is not None:
            return expired
        status = rec.get("status")
        if status in ("pending", "awaiting_double_confirm"):
            rec["status"] = "denied"
            rec["resolved_at"] = now
            if reason_stripped:
                rec["deny_reason"] = reason_stripped[:2000]
            items[i] = rec
            _save_all(items, tenant_id=tid)
            return ApprovalMutation(record=rec, changed=True)
        if status == "denied":
            return ApprovalMutation(record=rec, changed=False)
        if status == "approved":
            return ApprovalMutation(record=rec, changed=False, conflict=True)
        return None
    return None
