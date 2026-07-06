"""B2.7 — Unified policy.violation audit records."""

from __future__ import annotations

from typing import Any


def record_policy_violation(
    *,
    tool: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    path: str | None = None,
    error_code: str | None = None,
    message_pt: str | None = None,
    violation: str | None = None,
    bundle_id: str | None = None,
    bundle_version: int | None = None,
    args: dict[str, Any] | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "tool": tool,
        "error_code": error_code,
        "message_pt": message_pt,
        "violation": violation,
        "path": path,
        "bundle_id": bundle_id,
        "bundle_version": bundle_version,
    }
    if args:
        metadata["args_keys"] = sorted(args.keys())[:20]
    try:
        from app.audit_service import append_audit_event

        append_audit_event(
            action="policy.violation",
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            resource=violation or tool,
            metadata=metadata,
        )
    except Exception:
        pass
    try:
        from app.shared.business_metrics import inc_policy_violation

        inc_policy_violation(error_code)
    except Exception:
        pass
