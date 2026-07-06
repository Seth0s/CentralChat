"""H1/H3 — Admin routes: audit export + policy + compliance + break-glass."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.auth import (
    create_admin_user,
    list_auth_users,
    reset_admin_user_password,
    revoke_user_refresh_sessions,
    update_admin_user,
)
from app.admin_ops import build_deploy_status
from app.audit_export_jobs import (
    create_audit_export_job,
    get_audit_export_job,
    get_audit_export_result,
    list_audit_export_jobs,
)
from app.audit_report import build_audit_report, export_audit_report_json, export_audit_report_pdf
from app.audit_service import append_audit_event, export_audit_csv, export_audit_json, list_audit_events
from app.config import (
    CENTRAL_AIR_GAP_MODE,
    CENTRAL_DATA_RESIDENCY,
    CENTRAL_LLM_ENDPOINT_REGION,
    CENTRAL_TELEMETRY_DISABLED,
)
from app.shared.break_glass import grant_break_glass, list_active_break_glass, revoke_break_glass
from app.shared.compliance_packs import apply_compliance_pack, get_compliance_pack, list_compliance_packs, preview_compliance_pack
from app.shared.inference_governance import (
    configure_provider,
    get_global_models_allowlist,
    governance_summary,
    list_providers_public,
    set_global_models_allowlist,
)
from app.shared.secrets_admin import (
    delete_secret,
    list_known_integration_secret_keys,
    list_secrets_metadata,
    secrets_storage_info,
    test_provider_connection,
    test_secret,
    upsert_secret,
)
from app.org_memberships import (
    create_group,
    create_project,
    delete_membership,
    find_project_lead_user_id,
    list_org_health,
    list_org_tree,
    list_project_members,
    list_user_memberships,
    patch_group,
    patch_project,
    require_can_manage_project,
    upsert_membership,
)
from app.shared.siem_outbox import process_siem_outbox, siem_outbox_summary
from app.shared.policy_engine import policies_public_snapshot
from app.shared.policy_bundle_store import (
    create_policy_draft,
    get_active_policy_summary,
    get_policy_bundle_detail,
    list_policy_bundle_history,
    publish_policy_draft,
    rollback_policy_bundle,
    update_policy_draft,
)
from app.shared.rbac import get_current_role, require_any_role
from app.shared.pg_tenant import memory_db_enabled, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub
from app.session_acl import (
    delete_session_acl,
    list_session_acl,
    upsert_session_acl,
    user_can_access_session,
)
from app.sessions import get_session
from app.team_requests import (
    VALID_REQUEST_TYPES,
    add_team_request_comment,
    create_team_request,
    get_team_request,
    list_team_request_comments,
    list_team_requests,
    resolve_team_request,
)
from app.tenant_quota import get_usage_summary_24h

router_admin = APIRouter()


def _admin_user_payload(user: object) -> dict:
    return {
        "id": getattr(user, "id"),
        "email": getattr(user, "email"),
        "client_id": getattr(user, "client_id"),
        "display_name": getattr(user, "display_name"),
        "active": getattr(user, "active"),
        "role": getattr(user, "role"),
    }


def _audit_admin_user(action: str, *, tenant_id: str, target: object | str, metadata: dict | None = None) -> None:
    target_id = str(getattr(target, "id", target))
    meta = dict(metadata or {})
    if not isinstance(target, str):
        meta.setdefault("target_user_id", target_id)
        meta.setdefault("target_email", getattr(target, "email", ""))
        meta.setdefault("target_role", getattr(target, "role", ""))
        meta.setdefault("target_active", getattr(target, "active", None))
    append_audit_event(
        action=action,
        tenant_id=tenant_id,
        user_id=get_current_sub(),
        resource=target_id,
        metadata=meta,
    )


def _audit_secret(action: str, *, tenant_id: str, secret_key: str, metadata: dict | None = None) -> None:
    append_audit_event(
        action=action,
        tenant_id=tenant_id,
        user_id=get_current_sub(),
        resource=secret_key,
        metadata={"secret_key": secret_key, **dict(metadata or {})},
    )


def _audit_inference_provider(action: str, *, tenant_id: str, provider_id: str, metadata: dict | None = None) -> None:
    append_audit_event(
        action=action,
        tenant_id=tenant_id,
        user_id=get_current_sub(),
        resource=provider_id,
        metadata={"provider_id": provider_id, **dict(metadata or {})},
    )


def _audit_project_membership(
    action: str,
    *,
    tenant_id: str,
    project_id: str,
    user_id: str,
    metadata: dict | None = None,
) -> None:
    append_audit_event(
        action=action,
        tenant_id=tenant_id,
        user_id=get_current_sub(),
        resource=project_id,
        metadata={
            "project_id": project_id,
            "target_user_id": user_id,
            **dict(metadata or {}),
        },
    )


class BreakGlassGrantBody(BaseModel):
    path_pattern: str = Field(..., min_length=1, max_length=500)
    reason: str = Field(..., min_length=3, max_length=2000)
    user_id: str | None = Field(default=None, max_length=200)
    ttl_hours: float | None = Field(default=None, ge=0.25, le=24)


class ComplianceApplyBody(BaseModel):
    pack_id: str = Field(..., min_length=2, max_length=64)


class InferenceProviderPatchBody(BaseModel):
    api_key: str | None = Field(default=None, max_length=512, description="Write-only; omit to keep")
    enabled: bool | None = None


class SecretUpsertBody(BaseModel):
    value: str = Field(..., min_length=1, max_length=4096)
    label: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=64)


class GlobalModelsAllowlistBody(BaseModel):
    model_ids: list[str] = Field(default_factory=list, max_length=5000)


class OrgGroupBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class OrgGroupPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class OrgProjectBody(BaseModel):
    group_id: str = Field(..., min_length=8, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    repository_url: str | None = Field(default=None, max_length=1000)


class OrgProjectPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    repository_url: str | None = Field(default=None, max_length=1000)


class ProjectMemberBody(BaseModel):
    role: str = Field(..., min_length=3, max_length=32)


class SessionAclUpsertBody(BaseModel):
    principal_type: str = Field(..., pattern="^(user|role)$")
    principal_id: str = Field(..., min_length=1, max_length=200)
    access_level: str = Field(default="read", pattern="^(read|write|admin)$")


class TeamRequestCreateBody(BaseModel):
    request_type: str = Field(..., min_length=3, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=4000)
    project_id: str | None = Field(default=None, max_length=80)
    session_id: str | None = Field(default=None, max_length=200)
    work_item_id: str | None = Field(default=None, max_length=200)
    assignee_id: str | None = Field(default=None, max_length=80)


class TeamRequestResolveBody(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=4000)
    status: str = Field(default="resolved", pattern="^(resolved|cancelled|in_discussion)$")


class TeamRequestCommentBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class PolicyRepoRuleBody(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=500)
    read: str | None = Field(default=None, max_length=32)
    write: str | None = Field(default=None, max_length=32)
    approval: str | None = Field(default=None, max_length=32)


class PolicyDraftBody(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    repos: list[PolicyRepoRuleBody] = Field(default_factory=list)
    tools: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


class PolicyRollbackBody(BaseModel):
    version: int = Field(..., ge=1, le=10000)


class AuditExportCreateBody(BaseModel):
    format: str = Field(default="csv", pattern="^(csv|json)$")
    since: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=80)
    action: str | None = Field(default=None, max_length=120)
    path_prefix: str | None = Field(default=None, max_length=500)


class AdminUserCreateBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=512)
    display_name: str | None = Field(default=None, max_length=200)
    role: str = Field(default="developer", max_length=32)


class AdminUserPatchBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=32)
    active: bool | None = None


class AdminUserResetPasswordBody(BaseModel):
    password: str = Field(..., min_length=8, max_length=512)


@router_admin.get("/admin/inference/status", tags=["OpsDashboard"])
def admin_inference_status() -> dict:
    """Summary of providers and allowlists (admin)."""
    require_any_role("admin", "auditor")
    return governance_summary()


@router_admin.get("/admin/inference/providers", tags=["OpsDashboard"])
def admin_inference_providers_list() -> dict:
    require_any_role("admin", "auditor")
    items = list_providers_public()
    return {"items": items, "count": len(items)}


@router_admin.put("/admin/inference/providers/{provider_id}", tags=["OpsDashboard"])
def admin_inference_provider_upsert(provider_id: str, body: InferenceProviderPatchBody) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        provider = configure_provider(
            provider_id,
            api_key=body.api_key,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_inference_provider(
        "admin.inference.provider.updated",
        tenant_id=tid,
        provider_id=provider_id.strip().lower(),
        metadata={
            "rotated_key": body.api_key is not None,
            "enabled": body.enabled,
        },
    )
    return {"provider": provider, "ok": True}


@router_admin.post("/admin/inference/providers/{provider_id}/test", tags=["OpsDashboard"])
def admin_inference_provider_test(provider_id: str) -> dict:
    require_any_role("admin")
    try:
        result = test_provider_connection(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"provider_id": provider_id.strip().lower(), **result}


@router_admin.get("/admin/secrets", tags=["OpsDashboard"])
def admin_secrets_list() -> dict:
    require_any_role("admin", "auditor")
    tid = resolve_pg_tenant_id()
    items = list_secrets_metadata(tenant_id=tid)
    return {
        "items": items,
        "count": len(items),
        "integration_keys_catalog": list_known_integration_secret_keys(),
        "storage": secrets_storage_info(),
    }


@router_admin.put("/admin/secrets/{secret_key}", tags=["OpsDashboard"])
def admin_secrets_upsert(secret_key: str, body: SecretUpsertBody) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        item = upsert_secret(
            secret_key,
            value=body.value,
            label=body.label,
            category=body.category,
            updated_by=get_current_sub(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_secret(
        "admin.secret.rotated",
        tenant_id=tid,
        secret_key=secret_key.strip().lower(),
        metadata={"category": item.get("category"), "label": item.get("label")},
    )
    return {"secret": item, "ok": True}


@router_admin.delete("/admin/secrets/{secret_key}", tags=["OpsDashboard"])
def admin_secrets_delete(secret_key: str) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        ok = delete_secret(secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="secret_not_found")
    _audit_secret(
        "admin.secret.revoked",
        tenant_id=tid,
        secret_key=secret_key.strip().lower(),
        metadata={},
    )
    return {"ok": True, "key": secret_key.strip().lower()}


@router_admin.post("/admin/secrets/{secret_key}/test", tags=["OpsDashboard"])
def admin_secrets_test(secret_key: str) -> dict:
    require_any_role("admin")
    try:
        result = test_secret(secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"key": secret_key.strip().lower(), **result}


@router_admin.get("/admin/inference/models/global", tags=["OpsDashboard"])
def admin_inference_global_models_get() -> dict:
    require_any_role("admin", "auditor")
    allowlist = get_global_models_allowlist()
    return {
        "model_ids": sorted(allowlist) if allowlist else [],
        "restricted": allowlist is not None,
    }


@router_admin.put("/admin/inference/models/global", tags=["OpsDashboard"])
def admin_inference_global_models_put(body: GlobalModelsAllowlistBody) -> dict:
    require_any_role("admin")
    cleaned = set_global_models_allowlist(body.model_ids)
    return {"model_ids": cleaned, "restricted": bool(cleaned), "ok": True}


@router_admin.get("/admin/org/tree", tags=["OpsDashboard"])
def admin_org_tree() -> dict:
    """Organization tree visible to the current user scope."""
    require_any_role("developer", "lead", "auditor", "admin")
    return list_org_tree()


@router_admin.get("/admin/org/health", tags=["OpsDashboard"])
def admin_org_health() -> dict:
    """Organization governance health visible to the current user scope."""
    require_any_role("lead", "auditor", "admin")
    return list_org_health()


@router_admin.get("/admin/users", tags=["OpsDashboard"])
def admin_users_list(
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    require_any_role("admin", "lead", "auditor")
    try:
        rows = list_auth_users(client_id=resolve_pg_tenant_id(), q=q, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    items = [
        {
            "id": u.id,
            "email": u.email,
            "client_id": u.client_id,
            "display_name": u.display_name,
            "active": u.active,
            "role": u.role,
        }
        for u in rows
    ]
    return {"items": items, "count": len(items)}


@router_admin.post("/admin/users", tags=["OpsDashboard"])
def admin_users_create(body: AdminUserCreateBody) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        user = create_admin_user(
            email=body.email,
            password=body.password,
            client_id=tid,
            display_name=body.display_name,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _audit_admin_user("admin.user.created", tenant_id=tid, target=user, metadata={"membership_created": False})
    return {"user": _admin_user_payload(user), "ok": True, "membership_created": False}


@router_admin.patch("/admin/users/{user_id}", tags=["OpsDashboard"])
def admin_users_patch(user_id: str, body: AdminUserPatchBody) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    if body.role is not None and get_current_sub() == user_id:
        raise HTTPException(status_code=403, detail="self_role_change_forbidden")
    try:
        user = update_admin_user(
            user_id=user_id,
            client_id=tid,
            display_name=body.display_name,
            role=body.role,
            active=body.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    sessions_revoked = bool(body.active is False or body.role is not None)
    if sessions_revoked:
        revoke_user_refresh_sessions(user_id=user.id)
    _audit_admin_user(
        "admin.user.updated",
        tenant_id=tid,
        target=user,
        metadata={
            "changed_fields": [
                key
                for key, value in {
                    "display_name": body.display_name,
                    "role": body.role,
                    "active": body.active,
                }.items()
                if value is not None
            ],
            "sessions_revoked": sessions_revoked,
        },
    )
    return {"user": _admin_user_payload(user), "ok": True, "sessions_revoked": sessions_revoked}


@router_admin.post("/admin/users/{user_id}/reset-password", tags=["OpsDashboard"])
def admin_users_reset_password(user_id: str, body: AdminUserResetPasswordBody) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        ok = reset_admin_user_password(
            user_id=user_id,
            client_id=tid,
            password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="user_not_found")
    revoke_user_refresh_sessions(user_id=user_id)
    _audit_admin_user("admin.user.password_reset", tenant_id=tid, target=user_id, metadata={"sessions_revoked": True})
    return {"ok": True, "sessions_revoked": True}


@router_admin.post("/admin/users/{user_id}/revoke-sessions", tags=["OpsDashboard"])
def admin_users_revoke_sessions(user_id: str) -> dict:
    require_any_role("admin")
    tid = resolve_pg_tenant_id()
    try:
        revoke_user_refresh_sessions(user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_admin_user("admin.user.sessions_revoked", tenant_id=tid, target=user_id, metadata={})
    return {"ok": True, "sessions_revoked": True}


@router_admin.get("/admin/users/{user_id}/memberships", tags=["OpsDashboard"])
def admin_users_memberships(user_id: str) -> dict:
    require_any_role("admin", "lead", "auditor")
    tid = resolve_pg_tenant_id()
    try:
        items = list_user_memberships(user_id=user_id, tenant_id=tid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items, "count": len(items)}


@router_admin.post("/admin/groups", tags=["OpsDashboard"])
def admin_groups_create(body: OrgGroupBody) -> dict:
    require_any_role("admin")
    try:
        group = create_group(name=body.name, slug=body.slug, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"group": group, "ok": True}


@router_admin.patch("/admin/groups/{group_id}", tags=["OpsDashboard"])
def admin_groups_patch(group_id: str, body: OrgGroupPatchBody) -> dict:
    require_any_role("admin")
    try:
        group = patch_group(
            group_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")
    return {"group": group, "ok": True}


@router_admin.post("/admin/projects", tags=["OpsDashboard"])
def admin_projects_create(body: OrgProjectBody) -> dict:
    require_any_role("admin")
    try:
        project = create_project(
            group_id=body.group_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            repository_url=body.repository_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"project": project, "ok": True}


@router_admin.patch("/admin/projects/{project_id}", tags=["OpsDashboard"])
def admin_projects_patch(project_id: str, body: OrgProjectPatchBody) -> dict:
    tid = resolve_pg_tenant_id()
    require_can_manage_project(tenant_id=tid, project_id=project_id)
    try:
        project = patch_project(
            project_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            repository_url=body.repository_url,
            tenant_id=tid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")
    return {"project": project, "ok": True}


@router_admin.get("/admin/projects/{project_id}/members", tags=["OpsDashboard"])
def admin_project_members_list(project_id: str) -> dict:
    tid = resolve_pg_tenant_id()
    require_can_manage_project(tenant_id=tid, project_id=project_id)
    try:
        items = list_project_members(project_id, tenant_id=tid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items, "count": len(items)}


@router_admin.put("/admin/projects/{project_id}/members/{user_id}", tags=["OpsDashboard"])
def admin_project_members_put(project_id: str, user_id: str, body: ProjectMemberBody) -> dict:
    tid = resolve_pg_tenant_id()
    require_can_manage_project(tenant_id=tid, project_id=project_id)
    try:
        before_items = list_project_members(project_id, tenant_id=tid)
        before = next((item for item in before_items if item["user_id"] == user_id), None)
        membership = upsert_membership(
            user_id=user_id,
            scope_type="project",
            scope_id=project_id,
            role=body.role,
            tenant_id=tid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before_role = str(before["role"]) if before else None
    action = "project_member.added" if before is None else "project_member.role_changed"
    _audit_project_membership(
        action,
        tenant_id=tid,
        project_id=project_id,
        user_id=user_id,
        metadata={"from_role": before_role, "to_role": membership["role"]},
    )
    return {"membership": membership, "ok": True}


@router_admin.delete("/admin/projects/{project_id}/members/{user_id}", tags=["OpsDashboard"])
def admin_project_members_delete(project_id: str, user_id: str) -> dict:
    tid = resolve_pg_tenant_id()
    require_can_manage_project(tenant_id=tid, project_id=project_id)
    try:
        before_items = list_project_members(project_id, tenant_id=tid)
        before = next((item for item in before_items if item["user_id"] == user_id), None)
        ok = delete_membership(
            user_id=user_id,
            scope_type="project",
            scope_id=project_id,
            tenant_id=tid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="membership_not_found")
    _audit_project_membership(
        "project_member.removed",
        tenant_id=tid,
        project_id=project_id,
        user_id=user_id,
        metadata={"from_role": before["role"] if before else None},
    )
    return {"ok": True, "project_id": project_id, "user_id": user_id}


@router_admin.get("/admin/audit/events", tags=["OpsDashboard"])
def admin_audit_list(
    since: str | None = Query(default=None, description="7d, 24h, or ISO date"),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    path_prefix: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    require_any_role("viewer", "auditor", "admin", "developer", "approver")
    items = list_audit_events(
        since=since, user_id=user_id, action=action, path_prefix=path_prefix, limit=limit
    )
    return {"items": items, "count": len(items)}


@router_admin.get("/admin/audit/export", tags=["OpsDashboard"])
def admin_audit_export(
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    since: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    path_prefix: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
):
    require_any_role("auditor", "admin")
    rows = list_audit_events(
        since=since, user_id=user_id, action=action, path_prefix=path_prefix, limit=limit
    )
    if format == "json":
        body = export_audit_json(rows)
        return Response(content=body, media_type="application/json")
    body = export_audit_csv(rows)
    return PlainTextResponse(content=body, media_type="text/csv")


@router_admin.get("/admin/audit/report", tags=["OpsDashboard"])
def admin_audit_report(
    format: str = Query(default="json", pattern="^(json|pdf)$"),
    since: str | None = Query(default=None),
    path_prefix: str | None = Query(default=None, description="e.g. payment/"),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
):
    """H3 — structured audit report (JSON or PDF)."""
    require_any_role("auditor", "admin")
    report = build_audit_report(
        since=since,
        path_prefix=path_prefix,
        user_id=user_id,
        action=action,
        limit=limit,
    )
    if format == "pdf":
        body = export_audit_report_pdf(report)
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="audit-report.pdf"'},
        )
    return Response(content=export_audit_report_json(report), media_type="application/json")


@router_admin.get("/admin/policies", tags=["OpsDashboard"])
def admin_policies_show() -> dict:
    require_any_role("developer", "approver", "admin", "auditor", "viewer")
    return policies_public_snapshot()


@router_admin.get("/admin/usage/summary", tags=["OpsDashboard"])
def admin_usage_summary(window: str = Query(default="24h", pattern="^(24h|7d|30d)$")) -> dict:
    """H2/D4 — cost dashboard data (hourly rollup)."""
    require_any_role("admin", "auditor", "approver")
    return get_usage_summary_24h(window=window)


@router_admin.get("/admin/compliance/packs", tags=["OpsDashboard"])
def admin_compliance_packs_list() -> dict:
    require_any_role("admin", "auditor", "approver")
    return {"items": list_compliance_packs(), "count": len(list_compliance_packs())}


@router_admin.get("/admin/compliance/packs/{pack_id}", tags=["OpsDashboard"])
def admin_compliance_pack_show(pack_id: str) -> dict:
    require_any_role("admin", "auditor", "approver")
    pack = get_compliance_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="pack_not_found")
    return pack


@router_admin.get("/admin/compliance/packs/{pack_id}/preview", tags=["OpsDashboard"])
def admin_compliance_pack_preview(pack_id: str) -> dict:
    require_any_role("admin", "auditor", "approver")
    preview = preview_compliance_pack(pack_id)
    if not preview:
        raise HTTPException(status_code=404, detail="pack_not_found")
    return preview


@router_admin.post("/admin/compliance/apply", tags=["OpsDashboard"])
def admin_compliance_apply(body: ComplianceApplyBody) -> dict:
    require_any_role("admin")
    result = apply_compliance_pack(body.pack_id)
    if not result:
        raise HTTPException(status_code=404, detail="pack_not_found")
    return result


@router_admin.get("/admin/break-glass/active", tags=["OpsDashboard"])
def admin_break_glass_active(user_id: str | None = Query(default=None)) -> dict:
    require_any_role("admin", "auditor")
    items = list_active_break_glass(user_id=user_id)
    return {"items": items, "count": len(items)}


@router_admin.post("/admin/break-glass/grant", tags=["OpsDashboard"])
def admin_break_glass_grant(body: BreakGlassGrantBody) -> dict:
    require_any_role("admin")
    grant = grant_break_glass(
        path_pattern=body.path_pattern,
        reason=body.reason,
        user_id=body.user_id,
        ttl_hours=body.ttl_hours,
    )
    if not grant:
        raise HTTPException(status_code=400, detail="grant_failed")
    return grant


@router_admin.delete("/admin/break-glass/{grant_id}", tags=["OpsDashboard"])
def admin_break_glass_revoke(grant_id: str) -> dict:
    require_any_role("admin")
    if not revoke_break_glass(grant_id):
        raise HTTPException(status_code=404, detail="grant_not_found")
    return {"ok": True, "grant_id": grant_id}


@router_admin.get("/admin/deploy/residency", tags=["OpsDashboard"])
def admin_deploy_residency() -> dict:
    """H3 — data residency / air-gap runtime flags (read-only)."""
    require_any_role("admin", "auditor")
    return {
        "data_residency": CENTRAL_DATA_RESIDENCY,
        "llm_endpoint_region": CENTRAL_LLM_ENDPOINT_REGION,
        "telemetry_disabled": CENTRAL_TELEMETRY_DISABLED,
        "air_gap_mode": CENTRAL_AIR_GAP_MODE,
    }


def _session_acl_roles() -> None:
    require_any_role("lead", "admin")


def _session_read_roles() -> None:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer", "viewer")


@router_admin.get("/admin/sessions/{session_id}", tags=["OpsDashboard"])
def admin_session_detail(session_id: str) -> dict:
    _session_read_roles()
    tid = resolve_pg_tenant_id()
    if not user_can_access_session(
        session_id=session_id,
        role=get_current_role(),
        user_id=get_current_sub(),
        tenant_id=tid,
    ):
        raise HTTPException(status_code=403, detail="session_access_denied")
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    return {"session": session, "ok": True}


@router_admin.get("/admin/sessions/{session_id}/acl", tags=["OpsDashboard"])
def admin_session_acl_list(session_id: str) -> dict:
    _session_acl_roles()
    if not memory_db_enabled():
        return {"items": [], "count": 0}
    items = list_session_acl(session_id=session_id, tenant_id=resolve_pg_tenant_id())
    return {"items": items, "count": len(items)}


@router_admin.put("/admin/sessions/{session_id}/acl", tags=["OpsDashboard"])
def admin_session_acl_upsert(session_id: str, body: SessionAclUpsertBody) -> dict:
    _session_acl_roles()
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        entry = upsert_session_acl(
            session_id=session_id,
            principal_type=body.principal_type,
            principal_id=body.principal_id,
            access_level=body.access_level,
            tenant_id=resolve_pg_tenant_id(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    append_audit_event(
        action="session_acl.granted",
        tenant_id=resolve_pg_tenant_id(),
        user_id=get_current_sub(),
        resource=session_id,
        metadata={
            "principal_type": body.principal_type,
            "principal_id": body.principal_id,
            "access_level": body.access_level,
        },
    )
    return {"entry": entry, "ok": True}


@router_admin.delete(
    "/admin/sessions/{session_id}/acl/{principal_type}/{principal_id}",
    tags=["OpsDashboard"],
)
def admin_session_acl_delete(session_id: str, principal_type: str, principal_id: str) -> dict:
    _session_acl_roles()
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        removed = delete_session_acl(
            session_id=session_id,
            principal_type=principal_type,
            principal_id=principal_id,
            tenant_id=resolve_pg_tenant_id(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="acl_not_found")
    append_audit_event(
        action="session_acl.revoked",
        tenant_id=resolve_pg_tenant_id(),
        user_id=get_current_sub(),
        resource=session_id,
        metadata={"principal_type": principal_type, "principal_id": principal_id},
    )
    return {"ok": True}


@router_admin.get("/admin/requests", tags=["OpsDashboard"])
def admin_requests_list(
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
) -> dict:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer")
    if not memory_db_enabled():
        return {"items": [], "count": 0, "requests_enabled": False}
    items = list_team_requests(
        status=status,
        project_id=project_id,
        limit=limit,
        tenant_id=resolve_pg_tenant_id(),
    )
    return {"items": items, "count": len(items), "requests_enabled": True}


@router_admin.post("/admin/requests", tags=["OpsDashboard"])
def admin_requests_create(body: TeamRequestCreateBody) -> dict:
    require_any_role("developer", "lead", "admin")
    if body.request_type not in VALID_REQUEST_TYPES:
        raise HTTPException(status_code=422, detail="invalid_request_type")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    tid = resolve_pg_tenant_id()
    assignee_id = body.assignee_id
    if not assignee_id and body.project_id:
        assignee_id = find_project_lead_user_id(project_id=body.project_id, tenant_id=tid)
    try:
        item = create_team_request(
            request_type=body.request_type,
            title=body.title,
            body=body.body,
            project_id=body.project_id,
            session_id=body.session_id,
            work_item_id=body.work_item_id,
            assignee_id=assignee_id,
            tenant_id=tid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"request": item, "ok": True}


@router_admin.get("/admin/requests/{request_id}", tags=["OpsDashboard"])
def admin_requests_detail(request_id: str) -> dict:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    item = get_team_request(request_id, tenant_id=resolve_pg_tenant_id())
    if not item:
        raise HTTPException(status_code=404, detail="request_not_found")
    return {"request": item, "ok": True}


@router_admin.post("/admin/requests/{request_id}/comments", tags=["OpsDashboard"])
def admin_requests_comment(request_id: str, body: TeamRequestCommentBody) -> dict:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        comment = add_team_request_comment(request_id, body=body.body, tenant_id=resolve_pg_tenant_id())
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "request_not_found" else 422
        raise HTTPException(status_code=status, detail=code) from exc
    return {"comment": comment, "ok": True}


@router_admin.get("/admin/requests/{request_id}/comments", tags=["OpsDashboard"])
def admin_requests_comments_list(request_id: str) -> dict:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer")
    if not memory_db_enabled():
        return {"items": [], "count": 0}
    items = list_team_request_comments(request_id, tenant_id=resolve_pg_tenant_id())
    return {"items": items, "count": len(items)}


@router_admin.post("/admin/requests/{request_id}/resolve", tags=["OpsDashboard"])
def admin_requests_resolve(request_id: str, body: TeamRequestResolveBody) -> dict:
    require_any_role("lead", "admin", "auditor")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        item = resolve_team_request(
            request_id,
            resolution=body.resolution,
            status=body.status,
            tenant_id=resolve_pg_tenant_id(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="request_not_found")
    return {"request": item, "ok": True}


def _policy_payload(body: PolicyDraftBody) -> dict:
    return {
        "repos": [r.model_dump(exclude_none=True) for r in body.repos],
        "tools": body.tools,
    }


@router_admin.get("/admin/policies/active", tags=["OpsDashboard"])
def admin_policies_active() -> dict:
    require_any_role("developer", "lead", "auditor", "admin", "reviewer", "viewer")
    return get_active_policy_summary(tenant_id=resolve_pg_tenant_id())


@router_admin.get("/admin/policies/history", tags=["OpsDashboard"])
def admin_policies_history(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    require_any_role("lead", "auditor", "admin")
    items = list_policy_bundle_history(resolve_pg_tenant_id(), limit=limit)
    return {"items": items, "count": len(items)}


@router_admin.get("/admin/policies/bundles/{bundle_id}", tags=["OpsDashboard"])
def admin_policies_bundle_detail(bundle_id: str) -> dict:
    require_any_role("lead", "auditor", "admin")
    detail = get_policy_bundle_detail(bundle_id, tenant_id=resolve_pg_tenant_id())
    if not detail:
        raise HTTPException(status_code=404, detail="bundle_not_found")
    return {"bundle": detail, "ok": True}


@router_admin.post("/admin/policies/drafts", tags=["OpsDashboard"])
def admin_policies_draft_create(body: PolicyDraftBody) -> dict:
    require_any_role("lead", "admin")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        out = create_policy_draft(
            tenant_id=resolve_pg_tenant_id(),
            policies=_policy_payload(body),
            label=body.label,
            created_by=get_current_sub(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"bundle": out, "ok": True}


@router_admin.put("/admin/policies/drafts/{bundle_id}", tags=["OpsDashboard"])
def admin_policies_draft_update(bundle_id: str, body: PolicyDraftBody) -> dict:
    require_any_role("lead", "admin")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    detail = update_policy_draft(
        bundle_id,
        policies=_policy_payload(body),
        label=body.label,
        tenant_id=resolve_pg_tenant_id(),
    )
    if not detail:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return {"bundle": detail, "ok": True}


@router_admin.post("/admin/policies/drafts/{bundle_id}/publish", tags=["OpsDashboard"])
def admin_policies_draft_publish(bundle_id: str) -> dict:
    require_any_role("lead", "admin")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    out = publish_policy_draft(
        bundle_id,
        tenant_id=resolve_pg_tenant_id(),
        published_by=get_current_sub(),
    )
    if not out:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return {"bundle": out, "ok": True}


@router_admin.post("/admin/policies/rollback", tags=["OpsDashboard"])
def admin_policies_rollback(body: PolicyRollbackBody) -> dict:
    require_any_role("admin")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    out = rollback_policy_bundle(
        version=body.version,
        tenant_id=resolve_pg_tenant_id(),
        activated_by=get_current_sub(),
    )
    if not out:
        raise HTTPException(status_code=404, detail="version_not_found")
    return out


@router_admin.get("/admin/deploy/status", tags=["OpsDashboard"])
def admin_deploy_status() -> dict:
    require_any_role("admin", "auditor")
    return build_deploy_status(tenant_id=resolve_pg_tenant_id())


@router_admin.get("/admin/siem/outbox", tags=["OpsDashboard"])
def admin_siem_outbox_status() -> dict:
    require_any_role("admin", "auditor")
    summary = siem_outbox_summary(tenant_id=resolve_pg_tenant_id())
    return {"summary": summary, "ok": True}


@router_admin.post("/admin/siem/outbox/process", tags=["OpsDashboard"])
def admin_siem_outbox_process(batch_size: int = Query(default=50, ge=1, le=200)) -> dict:
    require_any_role("admin")
    counts = process_siem_outbox(batch_size=batch_size)
    return {"counts": counts, "ok": True}


@router_admin.post("/admin/audit/exports", tags=["OpsDashboard"])
def admin_audit_exports_create(body: AuditExportCreateBody) -> dict:
    require_any_role("auditor", "admin")
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")
    try:
        job = create_audit_export_job(
            format=body.format,
            since=body.since,
            user_id=body.user_id,
            action=body.action,
            path_prefix=body.path_prefix,
            tenant_id=resolve_pg_tenant_id(),
            requested_by=get_current_sub(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"job": job, "ok": True}


@router_admin.get("/admin/audit/exports", tags=["OpsDashboard"])
def admin_audit_exports_list(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    require_any_role("auditor", "admin")
    items = list_audit_export_jobs(tenant_id=resolve_pg_tenant_id(), limit=limit)
    return {"items": items, "count": len(items)}


@router_admin.get("/admin/audit/exports/{job_id}", tags=["OpsDashboard"])
def admin_audit_exports_show(job_id: str) -> dict:
    require_any_role("auditor", "admin")
    job = get_audit_export_job(job_id, tenant_id=resolve_pg_tenant_id())
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"job": job, "ok": True}


@router_admin.get("/admin/audit/exports/{job_id}/download", tags=["OpsDashboard"])
def admin_audit_exports_download(job_id: str) -> Response:
    require_any_role("auditor", "admin")
    job = get_audit_export_job(job_id, tenant_id=resolve_pg_tenant_id())
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="export_not_ready")
    body = get_audit_export_result(job_id, tenant_id=resolve_pg_tenant_id())
    if not body:
        raise HTTPException(status_code=404, detail="export_not_ready")
    fmt = str(job.get("format") or "csv")
    media = "text/csv" if fmt == "csv" else "application/json"
    ext = "csv" if fmt == "csv" else "json"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="audit-export-{job_id[:8]}.{ext}"'},
    )
