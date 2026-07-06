"""H1 — Tenant policy engine (paths, tools, models)."""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.config import CENTRAL_ROOT
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

DEFAULT_POLICIES: dict[str, Any] = {
    "repos": [
        {"pattern": "**/.env*", "read": "denied", "write": "denied"},
        {"pattern": "**/credentials/**", "read": "denied", "write": "denied"},
        {"pattern": "**/payment/**", "write": "approval_required", "approval": "dual"},
        {"pattern": "**/api/**", "approval": "dual"},
    ],
    "tools": {
        "terminal": {"denied_patterns": ["**/payment/**"]},
    },
    "models": {
        "allowlist": [],
    },
    "write_mode_default": "direct_write",
    "environments": {
        "production": {"write_mode": "pr_only"},
        "staging": {"write_mode": "pr_only"},
    },
}


@dataclass
class EnginePolicyResult:
    allowed: bool
    error_code: str | None = None
    message_pt: str | None = None
    violation: str | None = None


def _load_tenant_policies(tenant_id: str) -> dict[str, Any]:
    policies = dict(DEFAULT_POLICIES)
    try:
        from app.shared.policy_bundle_store import load_active_policies_from_pg

        bundle = load_active_policies_from_pg(tenant_id)
        if bundle:
            if isinstance(bundle.get("repos"), list):
                policies["repos"] = bundle["repos"]
            if isinstance(bundle.get("tools"), dict):
                policies["tools"] = {**policies.get("tools", {}), **bundle["tools"]}
            policies["_bundle_id"] = bundle.get("bundle_id")
            policies["_bundle_version"] = bundle.get("bundle_version")
            return policies
    except Exception:
        logger.debug("policy bundle load failed", exc_info=True)
    if memory_db_enabled():
        try:
            with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT features_json FROM tenant_config WHERE tenant_id=%s LIMIT 1",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    fj = row[0]
                    if isinstance(fj, str):
                        fj = json.loads(fj)
                    if isinstance(fj, dict) and isinstance(fj.get("policies"), dict):
                        policies.update(fj["policies"])
        except Exception:
            logger.debug("tenant_config policies load failed", exc_info=True)
    root = (CENTRAL_ROOT or "/tmp/central").strip()
    path = f"{root}/config/team_policies.json"
    try:
        with open(path, encoding="utf-8") as fh:
            file_pol = json.load(fh)
        if isinstance(file_pol, dict):
            if isinstance(file_pol.get("repos"), list):
                policies["repos"] = file_pol["repos"]
            if isinstance(file_pol.get("tools"), dict):
                policies["tools"] = {**policies.get("tools", {}), **file_pol["tools"]}
            if isinstance(file_pol.get("models"), dict):
                policies["models"] = {**policies.get("models", {}), **file_pol["models"]}
    except (OSError, json.JSONDecodeError):
        pass
    return policies


def _norm_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return ""
    return str(PurePosixPath(p))


def _match_glob(path: str, pattern: str) -> bool:
    pat = (pattern or "").strip()
    if not pat:
        return False
    norm = _norm_path(path)
    if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(path, pat):
        return True
    if pat.startswith("**/"):
        bare = pat[3:]
        if bare.endswith("/**"):
            prefix = bare[:-3].rstrip("/")
            if norm == prefix or norm.startswith(prefix + "/") or norm.startswith(prefix):
                return True
        base = norm.rsplit("/", 1)[-1]
        if fnmatch.fnmatch(norm, bare) or fnmatch.fnmatch(base, bare):
            return True
    return False


def _match_repo_rule(path: str, rule: dict[str, Any]) -> bool:
    pat = str(rule.get("pattern") or "")
    if not pat:
        return False
    return _match_glob(path, pat)


def _break_glass_bypass(
    path: str,
    *,
    tenant_id: str,
    tool: str | None = None,
) -> EnginePolicyResult | None:
    try:
        from app.shared.break_glass import break_glass_allows_path, record_break_glass_use

        grant = break_glass_allows_path(path, tenant_id=tenant_id)
        if grant:
            record_break_glass_use(grant, path=path, tool=tool)
            return EnginePolicyResult(allowed=True)
    except Exception:
        logger.debug("break_glass bypass check failed", exc_info=True)
    return None


def evaluate_path_policy(
    path: str,
    *,
    mode: str,
    tenant_id: str | None = None,
) -> EnginePolicyResult:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    norm = _norm_path(path)
    if not norm:
        return EnginePolicyResult(allowed=True)
    policies = _load_tenant_policies(tid)
    for rule in policies.get("repos") or []:
        if not isinstance(rule, dict):
            continue
        if not _match_repo_rule(norm, rule):
            continue
        decision = str(rule.get(mode) or rule.get("access") or "").strip().lower()
        if decision == "denied":
            bypass = _break_glass_bypass(norm, tenant_id=tid)
            if bypass:
                return bypass
            return EnginePolicyResult(
                allowed=False,
                error_code="policy_path_denied",
                message_pt=f"Acesso {mode} negado pela política da equipa: {norm}",
                violation=f"path.{mode}:{norm}",
            )
    return EnginePolicyResult(allowed=True)


def evaluate_tool_policy(
    tool: str,
    args: dict[str, Any],
    *,
    tenant_id: str | None = None,
    workspace_path: str | None = None,
    model_id: str | None = None,
) -> EnginePolicyResult:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    name = (tool or "").strip()
    policies = _load_tenant_policies(tid)

    allowlist = policies.get("models", {}).get("allowlist") if isinstance(policies.get("models"), dict) else []
    if isinstance(allowlist, list) and allowlist and model_id:
        mid = str(model_id).strip()
        if mid and mid not in allowlist:
            return EnginePolicyResult(
                allowed=False,
                error_code="policy_model_denied",
                message_pt=f"Modelo não permitido pela política: {mid}",
                violation=f"model:{mid}",
            )

    from app.config import CENTRAL_CLOUD_MODEL_ALLOWLIST, CENTRAL_CLOUD_MODEL_SENSITIVE_PATHS

    if model_id and CENTRAL_CLOUD_MODEL_ALLOWLIST:
        mid = str(model_id).strip()
        if mid and mid not in CENTRAL_CLOUD_MODEL_ALLOWLIST:
            for key in ("path", "cwd", "file", "target"):
                v = args.get(key)
                if isinstance(v, str) and v.strip():
                    for pat in CENTRAL_CLOUD_MODEL_SENSITIVE_PATHS:
                        if _match_glob(v.strip(), pat):
                            return EnginePolicyResult(
                                allowed=False,
                                error_code="policy_model_denied",
                                message_pt=(
                                    f"Modelo cloud '{mid}' não está na allowlist global "
                                    f"para paths sensíveis."
                                ),
                                violation=f"model.global:{mid}",
                            )

    paths: list[str] = []
    for key in ("path", "cwd", "file", "target"):
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            paths.append(v.strip())
    if workspace_path:
        paths.append(workspace_path)

    tool_cfg = policies.get("tools", {}).get(name) if isinstance(policies.get("tools"), dict) else None
    if isinstance(tool_cfg, dict):
        for pat in tool_cfg.get("denied_patterns") or []:
            for p in paths:
                if _match_glob(p, str(pat)):
                    bypass = _break_glass_bypass(p, tenant_id=tid, tool=name)
                    if bypass:
                        continue
                    return EnginePolicyResult(
                        allowed=False,
                        error_code="policy_tool_denied",
                        message_pt=f"Tool {name} bloqueada em {p} pela política.",
                        violation=f"tool.{name}:{p}",
                    )

    mode = "write" if name in ("write_file", "patch", "terminal") else "read"
    for p in paths:
        path_res = evaluate_path_policy(p, mode=mode, tenant_id=tid)
        if not path_res.allowed:
            return path_res
    return EnginePolicyResult(allowed=True)


def requires_dual_approval(path: str, *, tenant_id: str | None = None) -> bool:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    norm = _norm_path(path)
    if not norm:
        return False
    policies = _load_tenant_policies(tid)
    for rule in policies.get("repos") or []:
        if not isinstance(rule, dict):
            continue
        if not _match_repo_rule(norm, rule):
            continue
        if str(rule.get("approval") or "").strip().lower() == "dual":
            return True
    return False


def resolve_write_mode(path: str, *, tenant_id: str | None = None) -> str:
    """direct_write | pr_only (per-path rule or tenant default)."""
    from app.config import CENTRAL_APP_ENV, CENTRAL_WRITE_MODE_DEFAULT

    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    norm = _norm_path(path)
    policies = _load_tenant_policies(tid)
    for rule in policies.get("repos") or []:
        if not isinstance(rule, dict) or not norm:
            continue
        if not _match_repo_rule(norm, rule):
            continue
        wm = str(rule.get("write_mode") or "").strip().lower()
        if wm in ("direct_write", "pr_only"):
            return wm
    envs = policies.get("environments") if isinstance(policies.get("environments"), dict) else {}
    env_key = "production" if CENTRAL_APP_ENV in ("production", "prod") else CENTRAL_APP_ENV
    env_cfg = envs.get(env_key) if isinstance(envs, dict) else None
    if isinstance(env_cfg, dict):
        wm = str(env_cfg.get("write_mode") or "").strip().lower()
        if wm in ("direct_write", "pr_only"):
            return wm
    default = str(policies.get("write_mode_default") or CENTRAL_WRITE_MODE_DEFAULT).strip().lower()
    return default if default in ("direct_write", "pr_only") else "direct_write"


def policies_public_snapshot(*, tenant_id: str | None = None) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    pol = _load_tenant_policies(tid)
    return {
        "tenant_id": tid,
        "repos": pol.get("repos") or [],
        "tools": pol.get("tools") or {},
        "models": pol.get("models") or {},
        "write_mode_default": pol.get("write_mode_default") or "direct_write",
        "environments": pol.get("environments") or {},
        "note_pt": "Avaliado antes de cada tool call; violações geram policy.violation no audit.",
    }
