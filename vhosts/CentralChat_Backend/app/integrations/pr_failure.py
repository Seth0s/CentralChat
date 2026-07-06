"""C2.3 — PR/MR failure → work item + webhook (no silent local write)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.audit_service import append_audit_event
from app.shared.secret_resolver import (
    resolve_quota_webhook_url,
    resolve_siem_webhook_urls,
)
from app.work_queue import create_work_item

logger = logging.getLogger(__name__)


def _notify_webhooks(payload: dict[str, Any]) -> None:
    urls = [u for u in (resolve_quota_webhook_url(), *resolve_siem_webhook_urls()) if u]
    body = json.dumps(payload, ensure_ascii=False)
    for url in urls:
        try:
            httpx.post(url, content=body, headers={"Content-Type": "application/json"}, timeout=5.0)
        except Exception:
            logger.debug("pr_failure webhook failed url=%s", url, exc_info=True)


def handle_pr_failure(
    approval_rec: dict[str, Any],
    pr_result: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, Any]:
    approval_id = str(approval_rec.get("approval_id") or "")
    body = approval_rec.get("payload") if isinstance(approval_rec.get("payload"), dict) else {}
    path = str(body.get("path") or "")
    err = str(pr_result.get("error") or "pr_failed")
    detail = str(pr_result.get("detail") or "")[:500]
    title = f"PR falhou: {path.split('/')[-1] or approval_id[:8]}"
    description = (
        f"Approval `{approval_id}` em modo pr_only falhou ao criar PR.\n\n"
        f"Erro: {err}\n{detail}\n\n"
        f"Path: {path}\n"
        "Acção manual necessária — write local foi bloqueado."
    )
    wi = create_work_item(
        title=title,
        description=description,
        priority="high",
        session_id=str(approval_rec.get("session_id") or "") or None,
        tenant_id=tenant_id,
    )
    append_audit_event(
        action="git.pr_failed",
        tenant_id=tenant_id,
        approval_id=approval_id or None,
        work_item_id=str(wi.get("id") or ""),
        resource=path or None,
        metadata={"error": err, "detail": detail, "pr_result": pr_result},
    )
    _notify_webhooks(
        {
            "source": "centralchat",
            "action": "git.pr_failed",
            "tenant_id": tenant_id,
            "approval_id": approval_id,
            "work_item_id": wi.get("id"),
            "error": err,
            "path": path,
        }
    )
    try:
        from app.shared.siem_outbox import enqueue_siem_event

        enqueue_siem_event(
            action="git.pr_failed",
            tenant_id=tenant_id,
            metadata={
                "approval_id": approval_id,
                "work_item_id": wi.get("id"),
                "error": err,
                "path": path,
            },
        )
    except Exception:
        pass
    return {"ok": False, "mode": "pr_only", "work_item": wi, "error": err}
