"""H2 — Integration routes: Git PR/MR, CI webhooks."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import CENTRAL_CI_WEBHOOK_SECRET
from app.integrations.git_service import create_github_pr, create_gitlab_mr, maybe_create_pr_after_approval
from app.shared.approvals_store import get_approval, resolve_tenant_id_for_store
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit
from app.shared.rbac import require_any_role
from app.work_queue import create_work_item

logger = logging.getLogger(__name__)

router_integrations = APIRouter()


class GitPrBody(BaseModel):
    approval_id: str = Field(..., min_length=8)
    base_branch: str = Field(default="main", max_length=120)


class GitMrBody(BaseModel):
    approval_id: str = Field(..., min_length=8)
    target_branch: str = Field(default="main", max_length=120)


class CiWebhookBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    pipeline_url: str | None = Field(default=None, max_length=2000)
    repo: str | None = Field(default=None, max_length=500)
    status: str = Field(default="failed", max_length=32)


def _verify_ci_signature(raw: bytes, signature: str | None) -> bool:
    secret = (CENTRAL_CI_WEBHOOK_SECRET or "").strip()
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, provided)


@router_integrations.post("/integrations/github/pr", tags=["OpsDashboard"])
def integrations_github_pr(body: GitPrBody) -> dict[str, Any]:
    require_any_role("approver", "admin", "developer")
    tid = resolve_tenant_id_for_store()
    rec = get_approval(body.approval_id, tenant_id=tid)
    if not rec:
        raise HTTPException(status_code=404, detail="approval_not_found")
    out = create_github_pr(approval_rec=rec, tenant_id=tid, base_branch=body.base_branch)
    if not out.get("ok"):
        raise HTTPException(status_code=502, detail=out.get("error") or "github_pr_failed")
    write_orchestrator_audit(
        {
            "event": "github_pr_created",
            "approval_id": body.approval_id,
            "pr_url": out.get("pr_url"),
            "tenant_id": tid,
        }
    )
    return out


@router_integrations.post("/integrations/gitlab/mr", tags=["OpsDashboard"])
def integrations_gitlab_mr(body: GitMrBody) -> dict[str, Any]:
    require_any_role("approver", "admin", "developer")
    tid = resolve_tenant_id_for_store()
    rec = get_approval(body.approval_id, tenant_id=tid)
    if not rec:
        raise HTTPException(status_code=404, detail="approval_not_found")
    out = create_gitlab_mr(approval_rec=rec, tenant_id=tid, target_branch=body.target_branch)
    if not out.get("ok"):
        raise HTTPException(status_code=502, detail=out.get("error") or "gitlab_mr_failed")
    write_orchestrator_audit(
        {
            "event": "gitlab_mr_created",
            "approval_id": body.approval_id,
            "mr_url": out.get("mr_url"),
            "tenant_id": tid,
        }
    )
    return out


@router_integrations.post("/webhooks/ci", tags=["OpsDashboard"])
async def webhooks_ci(
    request: Request,
    body: CiWebhookBody,
    x_central_signature: str | None = Header(default=None, alias="X-Central-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    if not _verify_ci_signature(raw, x_central_signature):
        raise HTTPException(status_code=401, detail="invalid_signature")
    tid = resolve_tenant_id_for_store()
    desc = f"CI {body.status}"
    if body.pipeline_url:
        desc += f"\n{body.pipeline_url}"
    try:
        item = create_work_item(
            title=body.title,
            description=desc,
            source="ci",
            labels=["ci", body.status],
            tenant_id=tid,
        )
        if body.pipeline_url:
            from app.work_queue import patch_work_item_external

            patch_work_item_external(
                str(item.get("id") or ""),
                external_url=body.pipeline_url,
                external_id=body.repo,
                tenant_id=tid,
            )
            item = {**item, "external_url": body.pipeline_url}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    write_orchestrator_audit(
        {
            "event": "ci_webhook_work_item",
            "work_item_id": item.get("id"),
            "pipeline_url": body.pipeline_url,
            "tenant_id": tid,
        }
    )
    return {"ok": True, "item": item}
