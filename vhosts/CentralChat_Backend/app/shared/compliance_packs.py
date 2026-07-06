"""H3 — Compliance pack templates (PCI, LGPD dev, ISO27001)."""

from __future__ import annotations

import copy
import logging
from typing import Any

from app.audit_service import append_audit_event
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub
from app.tenant import get_tenant_config, upsert_tenant_config

logger = logging.getLogger(__name__)

_PACK_PCI = {
    "id": "pci-dss",
    "name": "PCI-DSS (audit-ready)",
    "framework": "PCI DSS",
    "description_pt": (
        "Template audit-ready para código em scope PCI — não implica certificação. "
        "Bloqueio de credenciais, dual approval em payment/, terminal negado em paths sensíveis."
    ),
    "policies": {
        "repos": [
            {"pattern": "**/.env*", "read": "denied", "write": "denied"},
            {"pattern": "**/credentials/**", "read": "denied", "write": "denied"},
            {"pattern": "**/payment/**", "read": "approval_required", "write": "approval_required", "approval": "dual"},
            {"pattern": "**/cardholder/**", "read": "denied", "write": "denied"},
        ],
        "tools": {
            "terminal": {"denied_patterns": ["**/payment/**", "**/cardholder/**"]},
            "write_file": {"denied_patterns": ["**/.env*"]},
        },
        "models": {"allowlist": []},
        "write_mode_default": "pr_only",
    },
}

_PACK_LGPD = {
    "id": "lgpd-dev",
    "name": "LGPD desenvolvimento",
    "framework": "LGPD",
    "description_pt": "Restrições a PII em dev: paths de dados pessoais com leitura controlada e audit.",
    "policies": {
        "repos": [
            {"pattern": "**/pii/**", "read": "approval_required", "write": "denied"},
            {"pattern": "**/personal_data/**", "read": "approval_required", "write": "denied"},
            {"pattern": "**/gdpr/**", "read": "approval_required", "write": "denied"},
        ],
        "tools": {
            "memory": {"denied_patterns": ["**/pii/**", "**/personal_data/**"]},
        },
        "models": {"allowlist": []},
        "write_mode_default": "direct_write",
        "compliance": {"dlp_required": True, "audit_retention_days": 365},
    },
}

_PACK_ISO = {
    "id": "iso27001",
    "name": "ISO 27001 (audit-ready)",
    "framework": "ISO 27001",
    "description_pt": (
        "Template audit-ready ISO 27001 — não implica certificação. "
        "Controlo de mudanças: PR-only em produção, dual approval em API crítica."
    ),
    "policies": {
        "repos": [
            {"pattern": "**/api/**", "approval": "dual"},
            {"pattern": "**/infra/**", "write": "approval_required", "approval": "dual"},
            {"pattern": "**/secrets/**", "read": "denied", "write": "denied"},
        ],
        "tools": {
            "terminal": {"denied_patterns": ["**/secrets/**", "**/infra/prod/**"]},
        },
        "models": {"allowlist": []},
        "write_mode_default": "pr_only",
        "environments": {
            "production": {"write_mode": "pr_only"},
            "staging": {"write_mode": "pr_only"},
        },
    },
}

_COMPLIANCE_PACKS: dict[str, dict[str, Any]] = {
    _PACK_PCI["id"]: _PACK_PCI,
    _PACK_LGPD["id"]: _PACK_LGPD,
    _PACK_ISO["id"]: _PACK_ISO,
}


def list_compliance_packs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pack in _COMPLIANCE_PACKS.values():
        out.append(
            {
                "id": pack["id"],
                "name": pack["name"],
                "framework": pack["framework"],
                "description_pt": pack["description_pt"],
            }
        )
    return out


def get_compliance_pack(pack_id: str) -> dict[str, Any] | None:
    pid = (pack_id or "").strip().lower()
    pack = _COMPLIANCE_PACKS.get(pid)
    if not pack:
        return None
    return copy.deepcopy(pack)


def _merge_policies(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key in ("repos", "tools", "models", "environments", "compliance"):
        if key in overlay:
            if key == "repos" and isinstance(overlay["repos"], list):
                existing = merged.get("repos") if isinstance(merged.get("repos"), list) else []
                merged["repos"] = existing + overlay["repos"]
            elif key == "tools" and isinstance(overlay["tools"], dict):
                tools = merged.get("tools") if isinstance(merged.get("tools"), dict) else {}
                tools.update(overlay["tools"])
                merged["tools"] = tools
            elif key == "environments" and isinstance(overlay["environments"], dict):
                envs = merged.get("environments") if isinstance(merged.get("environments"), dict) else {}
                envs.update(overlay["environments"])
                merged["environments"] = envs
            else:
                merged[key] = overlay[key]
    for scalar in ("write_mode_default",):
        if scalar in overlay:
            merged[scalar] = overlay[scalar]
    return merged


def preview_compliance_pack(pack_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    """C3.8 — diff de políticas antes de apply."""
    pack = get_compliance_pack(pack_id)
    if not pack:
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    existing = get_tenant_config(tid)
    features = dict(existing.features_json) if existing else {}
    current_policies = features.get("policies") if isinstance(features.get("policies"), dict) else {}
    merged = _merge_policies(current_policies, pack["policies"])
    return {
        "tenant_id": tid,
        "pack_id": pack_id,
        "pack_name": pack.get("name"),
        "framework": pack.get("framework"),
        "audit_ready_notice": "Templates audit-ready — não implicam certificação PCI/ISO.",
        "current_policies": current_policies,
        "merged_policies": merged,
        "rollback_hint": (
            "Para reverter: remova o pack de compliance_packs_applied e restaure policies "
            "anteriores via export JSON ou backup tenant_config."
        ),
    }


def apply_compliance_pack(pack_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    pack = get_compliance_pack(pack_id)
    if not pack:
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    existing = get_tenant_config(tid)
    features = dict(existing.features_json) if existing else {}
    current_policies = features.get("policies") if isinstance(features.get("policies"), dict) else {}
    merged = _merge_policies(current_policies, pack["policies"])
    features["policies"] = merged
    applied = list(features.get("compliance_packs_applied") or [])
    if pack_id not in applied:
        applied.append(pack_id)
    features["compliance_packs_applied"] = applied
    upsert_tenant_config(tid, features_json=features)
    actor = (get_current_sub() or "system").strip()
    append_audit_event(
        action="compliance.pack_applied",
        tenant_id=tid,
        resource=pack_id,
        metadata={"pack_id": pack_id, "applied_by": actor, "framework": pack.get("framework")},
    )
    return {
        "tenant_id": tid,
        "pack_id": pack_id,
        "pack_name": pack.get("name"),
        "framework": pack.get("framework"),
        "policies": merged,
        "compliance_packs_applied": applied,
    }
