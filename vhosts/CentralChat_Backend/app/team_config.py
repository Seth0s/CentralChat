"""Fase 3 / H1b / P4 — Team catalog API (agents, skills, governed rules, lifecycle)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.memory_service import (
    approve_team_rule,
    create_manual_team_rule,
    create_team_agent_draft,
    create_team_skill_draft,
    list_team_agents,
    list_team_agents_catalog,
    list_team_rules,
    list_team_skills,
    list_team_skills_catalog,
    patch_team_agent_draft,
    patch_team_rule_pending,
    patch_team_skill_draft,
    publish_team_agent,
    publish_team_skill,
    reject_team_rule,
    submit_team_agent_review,
    submit_team_skill_review,
    team_rules_counts,
)
from app.shared.catalog_limits import catalog_prompt_max_chars, truncate_catalog_prompt
from app.shared.pg_tenant import memory_db_enabled
from app.shared.rbac import get_current_role, require_any_role
from app.shared.tenant_context import get_current_sub

router_team = APIRouter()

_CATALOG_PROMPT_MAX_CHARS = catalog_prompt_max_chars()

_CATALOG_READ_ROLES = ("viewer", "developer", "reviewer", "lead", "approver", "auditor", "admin")
_CATALOG_DRAFT_ROLES = ("developer", "lead", "admin")
_CATALOG_PUBLISH_ROLES = ("lead", "admin")
_RULE_REVIEW_ROLES = ("lead", "admin")


class TeamRuleCreateBody(BaseModel):
    pattern: str = Field(..., min_length=3, max_length=2000)


class TeamRulePatchBody(BaseModel):
    pattern: str = Field(..., min_length=3, max_length=2000)


class TeamRuleRejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class TeamAgentCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(default="", max_length=_CATALOG_PROMPT_MAX_CHARS)
    model_id: str | None = Field(default=None, max_length=256)


class TeamAgentPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    prompt: str | None = Field(default=None, max_length=_CATALOG_PROMPT_MAX_CHARS)
    model_id: str | None = Field(default=None, max_length=256)
    icon: str | None = Field(default=None, max_length=64)


class TeamSkillCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(default="", max_length=_CATALOG_PROMPT_MAX_CHARS)
    description: str = Field(default="", max_length=2000)


class TeamSkillPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    prompt: str | None = Field(default=None, max_length=_CATALOG_PROMPT_MAX_CHARS)
    description: str | None = Field(default=None, max_length=2000)


def _user_sub() -> str | None:
    sub = get_current_sub()
    return (sub or "").strip() or None


def _require_read() -> None:
    require_any_role(*_CATALOG_READ_ROLES)


def _require_draft() -> None:
    require_any_role(*_CATALOG_DRAFT_ROLES)
    if get_current_role() == "viewer":
        raise HTTPException(status_code=403, detail="viewer_read_only")


def _require_publish() -> None:
    require_any_role(*_CATALOG_PUBLISH_ROLES)


def _require_rule_review() -> None:
    require_any_role(*_RULE_REVIEW_ROLES)


def _pg_or_503() -> None:
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")


@router_team.get("/ui/team/agents", tags=["WidgetMVP"])
def ui_team_agents_list(
    status: str = Query(default="published", pattern="^(all|draft|review|published)$"),
) -> dict[str, Any]:
    _require_read()
    if status == "published":
        agents = list_team_agents()
    else:
        agents = list_team_agents_catalog(status=status)
    return {"items": agents, "count": len(agents), "status": status}


@router_team.post("/ui/team/agents", tags=["WidgetMVP"])
def ui_team_agents_create(body: TeamAgentCreateBody) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = create_team_agent_draft(
        name=body.name,
        prompt=body.prompt,
        model_id=body.model_id,
        created_by=_user_sub(),
    )
    if not row:
        raise HTTPException(status_code=400, detail="invalid_agent")
    return {"agent": row, "lifecycle_status": "draft"}


@router_team.patch("/ui/team/agents/{agent_id}", tags=["WidgetMVP"])
def ui_team_agents_patch(agent_id: str, body: TeamAgentPatchBody) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = patch_team_agent_draft(
        agent_id,
        name=body.name,
        prompt=body.prompt,
        model_id=body.model_id,
        icon=body.icon,
    )
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found_or_not_draft")
    return {"agent": row, "ok": True}


@router_team.post("/ui/team/agents/{agent_id}/submit-review", tags=["WidgetMVP"])
def ui_team_agents_submit_review(agent_id: str) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = submit_team_agent_review(agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found_or_not_draft")
    return {"ok": True, "agent": row}


@router_team.post("/ui/team/agents/{agent_id}/publish", tags=["WidgetMVP"])
def ui_team_agents_publish(agent_id: str) -> dict[str, Any]:
    _require_publish()
    _pg_or_503()
    row = publish_team_agent(agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found_or_not_in_review")
    return {"ok": True, "agent": row}


@router_team.get("/ui/team/skills", tags=["WidgetMVP"])
def ui_team_skills_list(
    status: str = Query(default="published", pattern="^(all|draft|review|published)$"),
) -> dict[str, Any]:
    _require_read()
    if status == "published":
        skills = list_team_skills()
    else:
        skills = list_team_skills_catalog(status=status)
    return {"items": skills, "count": len(skills), "status": status}


@router_team.post("/ui/team/skills", tags=["WidgetMVP"])
def ui_team_skills_create(body: TeamSkillCreateBody) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = create_team_skill_draft(
        name=body.name,
        prompt=body.prompt,
        description=body.description,
        created_by=_user_sub(),
    )
    if not row:
        raise HTTPException(status_code=400, detail="invalid_skill")
    return {"skill": row, "lifecycle_status": "draft"}


@router_team.patch("/ui/team/skills/{skill_id}", tags=["WidgetMVP"])
def ui_team_skills_patch(skill_id: str, body: TeamSkillPatchBody) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = patch_team_skill_draft(
        skill_id,
        name=body.name,
        prompt=body.prompt,
        description=body.description,
    )
    if not row:
        raise HTTPException(status_code=404, detail="skill_not_found_or_not_draft")
    return {"skill": row, "ok": True}


@router_team.post("/ui/team/skills/{skill_id}/submit-review", tags=["WidgetMVP"])
def ui_team_skills_submit_review(skill_id: str) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = submit_team_skill_review(skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="skill_not_found_or_not_draft")
    return {"ok": True, "skill": row}


@router_team.post("/ui/team/skills/{skill_id}/publish", tags=["WidgetMVP"])
def ui_team_skills_publish(skill_id: str) -> dict[str, Any]:
    _require_publish()
    _pg_or_503()
    row = publish_team_skill(skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="skill_not_found_or_not_in_review")
    return {"ok": True, "skill": row}


@router_team.get("/ui/team/rules", tags=["WidgetMVP"])
def ui_team_rules_list(
    status: str = Query(default="all", pattern="^(all|pending|approved|rejected)$"),
) -> dict[str, Any]:
    _require_read()
    items = list_team_rules(status=status)
    counts = team_rules_counts()
    return {"items": items, "counts": counts, "status": status}


@router_team.post("/ui/team/rules", tags=["WidgetMVP"])
def ui_team_rules_create(body: TeamRuleCreateBody) -> dict[str, Any]:
    _require_draft()
    _pg_or_503()
    row = create_manual_team_rule(pattern=body.pattern, proposed_by=_user_sub())
    if not row:
        raise HTTPException(status_code=400, detail="invalid_pattern")
    return {"rule": row}


@router_team.patch("/ui/team/rules/{rule_id}", tags=["WidgetMVP"])
def ui_team_rules_patch(rule_id: str, body: TeamRulePatchBody) -> dict[str, Any]:
    _require_rule_review()
    _pg_or_503()
    row = patch_team_rule_pending(rule_id, pattern=body.pattern)
    if not row:
        raise HTTPException(status_code=404, detail="rule_not_found_or_not_pending")
    return {"rule": row, "ok": True}


@router_team.post("/ui/team/rules/{rule_id}/approve", tags=["WidgetMVP"])
def ui_team_rules_approve(rule_id: str) -> dict[str, Any]:
    _require_rule_review()
    _pg_or_503()
    rec = approve_team_rule(rule_id, approved_by=_user_sub())
    if not rec:
        raise HTTPException(status_code=404, detail="rule_not_found_or_already_approved")
    return {"ok": True, "rule": rec}


@router_team.post("/ui/team/rules/{rule_id}/reject", tags=["WidgetMVP"])
def ui_team_rules_reject(rule_id: str, body: TeamRuleRejectBody) -> dict[str, Any]:
    _require_rule_review()
    _pg_or_503()
    rec = reject_team_rule(rule_id, reason=body.reason, rejected_by=_user_sub())
    if not rec:
        raise HTTPException(status_code=404, detail="rule_not_found_or_not_pending")
    return {"ok": True, "rule": rec}
