"""Approvals domain — HITL approval flow, action policy, tool-based creation.

Consolidated from:
  - action_policy.py          (policy flags, risk levels, APPROVAL_QUEUE_ACTION_IDS)
  - approval_via_tool.py      (tool-based approval creation, payload validation)
  - approvals.py              (API router)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import CENTRAL_APPROVAL_SEPARATION, SYSTEM_AGENT_POLICY_PATH, WRITE_CONFIG_MAX_CONTENT_BYTES
from app.connector import maybe_enqueue_shell_job_after_approval
from app.file_change_service import (
    FILE_PATCH_ACTION_ID,
    FILE_WRITE_ACTION_ID,
    enqueue_file_job_after_approval,
)
from app.shared.approvals_store import (
    approve_or_first_double_step,
    confirm_double,
    create_pending,
    get_approval,
    list_approvals,
    resolve_tenant_id_for_store,
    set_denied,
)
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit

# ═══════════════════════════════════════════════════════════════════
# ACTION POLICY
# ═══════════════════════════════════════════════════════════════════

# action_id que passam pela fila HITL do orquestrador (paridade: approval_via_tool + schema oneOf).
APPROVAL_QUEUE_ACTION_IDS: frozenset[str] = frozenset(
    {
        "process.signal",
        "systemd.unit.restart",
        "systemd.unit.stop",
        "systemd.unit.enable",
        "systemd.unit.disable",
        "systemd.user.unit.disable",
        "filesystem.path.read_external",
        "filesystem.path.write_config",
        "desktop.open_url",
        "desktop.notify",
        "network.endpoint.probe",
        "network.firewall.rule.apply",
        "network.firewall.policy.apply",
        "os.packages.install",
        "os.packages.upgrade_all",
        "os.power.reboot",
        "os.power.shutdown",
        "os.account.unix_useradd",
        "shell.exec",
        FILE_WRITE_ACTION_ID,
        FILE_PATCH_ACTION_ID,
    }
)

# Placeholders P2 (Fase 0 roadmap): risk_level no orquestrador se a policy não tiver entrada;
# em system-agent.json ficam com allowed:false até implementação das ondas P2-x.
P2_RESERVED_ACTION_IDS: frozenset[str] = frozenset(
    {
        "filesystem.path.mutate_external",
    }
)


def _load_policy() -> dict[str, Any]:
    path = SYSTEM_AGENT_POLICY_PATH
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def policy_flags_for_action(action_id: str) -> dict[str, bool]:
    """Flags usadas ao criar pendencias (alinhado a system-agent policy)."""
    cfg = _load_policy()
    entry = cfg.get("actions", {}).get(action_id) or {}
    if "requires_confirmation" in entry:
        requires_confirmation = bool(entry.get("requires_confirmation"))
    elif action_id in APPROVAL_QUEUE_ACTION_IDS:
        # desktop.* não estão na policy do system-agent; na fila exigem sempre humano.
        requires_confirmation = True
    else:
        requires_confirmation = False
    return {
        "requires_double_confirmation": bool(entry.get("requires_double_confirmation", False)),
        "requires_confirmation": requires_confirmation,
    }


def risk_level_for_action(action_id: str) -> str:
    """risk_level da policy; fallback conservador se policy em falta."""
    cfg = _load_policy()
    entry = cfg.get("actions", {}).get(action_id) or {}
    rl = str(entry.get("risk_level") or "").strip().upper()
    if rl in ("P0", "P1", "P2", "P3"):
        return rl
    if action_id in P2_RESERVED_ACTION_IDS:
        return "P2"
    if action_id == "systemd.unit.restart":
        return "P3"
    if action_id in ("os.power.reboot", "os.power.shutdown"):
        return "P3"
    if action_id in ("systemd.unit.enable", "systemd.unit.disable"):
        return "P3"
    if action_id == "systemd.unit.stop":
        return "P2"
    if action_id == "systemd.user.unit.disable":
        return "P2"
    if action_id == "filesystem.path.write_config":
        return "P2"
    if action_id == "filesystem.path.mutate_external":
        return "P2"
    if action_id == "network.firewall.rule.apply":
        return "P2"
    if action_id == "network.firewall.policy.apply":
        return "P3"
    if action_id == "os.packages.install":
        return "P2"
    if action_id == "os.packages.upgrade_all":
        return "P3"
    if action_id == "os.account.unix_useradd":
        return "P3"
    if action_id == "process.signal":
        return "P1"
    if action_id in (
        "desktop.open_url",
        "desktop.notify",
        "filesystem.path.read_external",
        "network.endpoint.probe",
    ):
        return "P1"
    if action_id == "shell.exec":
        return "P3"
    if action_id in (FILE_WRITE_ACTION_ID, FILE_PATCH_ACTION_ID):
        return "P1"
    return "P1"


# ═══════════════════════════════════════════════════════════════════
# APPROVAL VIA TOOL (Opcao B / ADR-005)
# ═══════════════════════════════════════════════════════════════════

_USER_DISABLE_UNIT_RE = re.compile(r"^[a-zA-Z0-9_.@-]+\.(timer|socket)$")
_PACKAGE_INSTALL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")
_UNIX_USERADD_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_BLOCKED_UNIX_USERADD = frozenset(
    {
        "root",
        "daemon",
        "bin",
        "sys",
        "sync",
        "games",
        "man",
        "mail",
        "www-data",
        "nobody",
        "dbus",
        "systemd-network",
        "systemd-resolve",
        "wheel",
        "sudo",
        "sshd",
        "adm",
        "lp",
        "uucp",
    }
)
_FIREWALL_POLICY_ZONE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

ALLOWED_APPROVAL_ACTION_IDS = APPROVAL_QUEUE_ACTION_IDS

_PAYLOAD_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "process.signal": frozenset({"pid"}),
    "systemd.unit.restart": frozenset({"unit"}),
    "systemd.unit.stop": frozenset({"unit"}),
    "systemd.unit.enable": frozenset({"unit"}),
    "systemd.unit.disable": frozenset({"unit"}),
    "systemd.user.unit.disable": frozenset({"unit"}),
    "filesystem.path.read_external": frozenset({"path"}),
    "filesystem.path.write_config": frozenset({"path", "content", "create_backup"}),
    "desktop.open_url": frozenset({"url"}),
    "desktop.notify": frozenset({"body", "title"}),
    "network.endpoint.probe": frozenset({"host", "port", "kind", "path"}),
    "network.firewall.rule.apply": frozenset({"port", "protocol", "direction", "action"}),
    "network.firewall.policy.apply": frozenset({"operation", "zone"}),
    "os.packages.install": frozenset({"package"}),
    "os.packages.upgrade_all": frozenset(),
    "os.power.reboot": frozenset(),
    "os.power.shutdown": frozenset(),
    "os.account.unix_useradd": frozenset({"username"}),
    "shell.exec": frozenset(
        {"mode", "argv", "sh_c", "cwd", "shell_session_id", "intent", "timeout_sec"}
    ),
    FILE_WRITE_ACTION_ID: frozenset({"path", "new_content", "diff", "summary", "change_kind"}),
    FILE_PATCH_ACTION_ID: frozenset({"path", "new_content", "diff", "summary", "change_kind"}),
}


def validate_and_normalize_approval_payload(
    action_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Valida e normaliza o payload da fila HITL para `action_id` em ALLOWED_APPROVAL_ACTION_IDS.
    Paridade: `create_approval_from_tool` e `POST /approvals/test` (quando action_id é conhecido).
    Rejeita chaves extra no payload (alinhado a JSON Schema additionalProperties: false).
    Devolve (store_payload, None) ou (None, codigo_erro).
    """
    allowed = _PAYLOAD_ALLOWED_KEYS.get(action_id)
    if allowed is None:
        return None, "unsupported_action_id"
    if action_id in ("os.packages.upgrade_all", "os.power.reboot", "os.power.shutdown"):
        if payload:
            return None, "payload_must_be_empty"
        return ({}, None)

    if action_id == "network.firewall.policy.apply":
        op = payload.get("operation")
        if op == "reload":
            if set(payload.keys()) != {"operation"}:
                return None, "payload_extra_fields"
            return ({"operation": "reload"}, None)
        if op == "set_default_zone":
            if set(payload.keys()) != {"operation", "zone"}:
                return None, "payload_extra_fields"
            zraw = payload.get("zone")
            if not isinstance(zraw, str):
                return None, "invalid_zone"
            z = zraw.strip()
            if not z or not _FIREWALL_POLICY_ZONE_RE.fullmatch(z):
                return None, "invalid_zone"
            return ({"operation": "set_default_zone", "zone": z}, None)
        return None, "invalid_firewall_policy_operation"

    extra = set(payload.keys()) - allowed
    if extra:
        return None, "payload_extra_fields"

    if action_id == "process.signal":
        pid = payload.get("pid")
        if not isinstance(pid, int) or pid < 2:
            return None, "invalid_pid"
        return ({"pid": pid, "signal": 15}, None)

    if action_id == "desktop.open_url":
        u = payload.get("url")
        if not isinstance(u, str):
            return None, "invalid_url"
        from app.actions import validate_open_url_for_queue

        ok_u, err_u, norm = validate_open_url_for_queue(u)
        if not ok_u:
            return None, str(err_u or "invalid_url")
        return ({"url": norm}, None)

    if action_id == "desktop.notify":
        body = payload.get("body")
        if not isinstance(body, str):
            return None, "invalid_notify_body"
        raw_title = payload.get("title")
        title_arg: str | None
        if raw_title is None:
            title_arg = None
        elif isinstance(raw_title, str):
            title_arg = raw_title
        else:
            return None, "invalid_notify_title"
        from app.actions import validate_notify_for_queue

        ok_n, err_n, store_payload = validate_notify_for_queue(body, title_arg)
        if not ok_n:
            return None, str(err_n or "invalid_notify")
        return (store_payload, None)

    if action_id == "filesystem.path.read_external":
        path_raw = payload.get("path")
        if not isinstance(path_raw, str):
            return None, "invalid_path"
        path_stripped = path_raw.strip()
        if not path_stripped or len(path_stripped) > 4096 or "\x00" in path_stripped:
            return None, "invalid_path"
        if not path_stripped.startswith("/"):
            return None, "path_must_be_absolute"
        segments = [p for p in path_stripped.split("/") if p != ""]
        if ".." in segments:
            return None, "path_invalid_component"
        return ({"path": path_stripped}, None)

    if action_id == "filesystem.path.write_config":
        path_raw = payload.get("path")
        if not isinstance(path_raw, str):
            return None, "invalid_path"
        path_stripped = path_raw.strip()
        if not path_stripped or len(path_stripped) > 4096 or "\x00" in path_stripped:
            return None, "invalid_path"
        if not path_stripped.startswith("/"):
            return None, "path_must_be_absolute"
        segments = [p for p in path_stripped.split("/") if p != ""]
        if ".." in segments:
            return None, "path_invalid_component"
        content = payload.get("content")
        if not isinstance(content, str):
            return None, "invalid_content"
        raw_cb = payload.get("create_backup")
        if raw_cb is None:
            create_backup = True
        elif isinstance(raw_cb, bool):
            create_backup = raw_cb
        else:
            return None, "invalid_create_backup"
        cap = min(65536, max(1, int(WRITE_CONFIG_MAX_CONTENT_BYTES)))
        try:
            as_bytes = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return None, "content_not_utf8"
        if len(as_bytes) > cap:
            return None, "content_too_large"
        return (
            {
                "path": path_stripped,
                "content": content,
                "create_backup": create_backup,
            },
            None,
        )

    if action_id == "network.endpoint.probe":
        host = payload.get("host")
        port = payload.get("port")
        kind = payload.get("kind")
        path_raw = payload.get("path")
        from app.actions import validate_probe_for_queue

        ok_p, err_p, store_p = validate_probe_for_queue(host, port, kind, path_raw)
        if not ok_p:
            return None, str(err_p or "invalid_probe")
        return (store_p, None)

    if action_id == "systemd.user.unit.disable":
        unit_raw = payload.get("unit")
        if not isinstance(unit_raw, str):
            return None, "invalid_unit"
        u = unit_raw.strip()
        if not u or len(u) > 256 or "\x00" in u or ".." in u or "/" in u:
            return None, "invalid_unit"
        if not _USER_DISABLE_UNIT_RE.fullmatch(u):
            return None, "user_disable_unit_must_be_timer_or_socket"
        return ({"unit": u}, None)

    if action_id == "network.firewall.rule.apply":
        port = payload.get("port")
        if not isinstance(port, int) or port < 1 or port > 65535:
            return None, "invalid_port"
        proto = payload.get("protocol")
        if proto not in ("tcp", "udp"):
            return None, "invalid_protocol"
        direction = payload.get("direction")
        if direction not in ("in", "out"):
            return None, "invalid_direction"
        act = payload.get("action")
        if act not in ("allow", "deny"):
            return None, "invalid_firewall_action"
        return (
            {
                "port": port,
                "protocol": proto,
                "direction": direction,
                "action": act,
            },
            None,
        )

    if action_id == "os.packages.install":
        pkg_raw = payload.get("package")
        if not isinstance(pkg_raw, str):
            return None, "invalid_package"
        p = pkg_raw.strip()
        if not p or len(p) > 200 or "\x00" in p or " " in p or "/" in p or "\n" in p:
            return None, "invalid_package"
        if not _PACKAGE_INSTALL_NAME_RE.fullmatch(p):
            return None, "invalid_package"
        return ({"package": p}, None)

    if action_id == "os.account.unix_useradd":
        raw = payload.get("username")
        if not isinstance(raw, str):
            return None, "invalid_username"
        u = raw.strip()
        if not u or "\x00" in u or len(u) > 32:
            return None, "invalid_username"
        if not _UNIX_USERADD_USERNAME_RE.fullmatch(u):
            return None, "invalid_username"
        if u in _BLOCKED_UNIX_USERADD:
            return None, "reserved_username"
        return ({"username": u}, None)

    if action_id in (
        "systemd.unit.restart",
        "systemd.unit.stop",
        "systemd.unit.enable",
        "systemd.unit.disable",
    ):
        unit = payload.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            return None, "invalid_unit"
        return ({"unit": unit.strip()}, None)

    if action_id in (FILE_WRITE_ACTION_ID, FILE_PATCH_ACTION_ID):
        path_raw = payload.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            return None, "invalid_path"
        path = path_raw.strip()
        if "\x00" in path or len(path) > 4096:
            return None, "invalid_path"
        new_content = payload.get("new_content")
        if not isinstance(new_content, str):
            return None, "invalid_content"
        if "\x00" in new_content:
            return None, "binary_file_rejected"
        cap = min(65536, max(1, int(WRITE_CONFIG_MAX_CONTENT_BYTES)))
        try:
            as_bytes = new_content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return None, "content_not_utf8"
        if len(as_bytes) > cap:
            return None, "content_too_large"
        diff = payload.get("diff")
        summary = payload.get("summary")
        change_kind = payload.get("change_kind")
        diff_text = str(diff) if diff is not None else ""
        if len(diff_text.encode("utf-8", errors="replace")) > 65536:
            diff_text = diff_text[:16000] + "\n… [diff truncated]"
        return (
            {
                "path": path,
                "new_content": new_content,
                "diff": diff_text,
                "summary": str(summary) if summary is not None else "",
                "change_kind": str(change_kind) if change_kind is not None else "patch",
            },
            None,
        )

    if action_id == "shell.exec":
        mode = payload.get("mode")
        if mode not in ("argv", "sh_c"):
            return None, "invalid_mode"
        argv = payload.get("argv")
        sh_c = payload.get("sh_c")
        if mode == "argv":
            if not isinstance(argv, list) or not argv:
                return None, "invalid_argv"
            if not all(isinstance(x, str) for x in argv):
                return None, "invalid_argv"
            sh_c = None
        else:
            if not isinstance(sh_c, str) or not sh_c.strip():
                return None, "invalid_sh_c"
            argv = None
        intent = payload.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return None, "invalid_intent"
        sid = payload.get("shell_session_id")
        sid_o = str(sid).strip() if isinstance(sid, str) else None
        cwd = payload.get("cwd")
        cwd_o = str(cwd).strip() if isinstance(cwd, str) and cwd.strip() else None
        to = payload.get("timeout_sec")
        to_i = int(to) if isinstance(to, int) else None
        if to_i is not None and not (1 <= to_i <= 600):
            to_i = None
        return (
            {
                "mode": mode,
                "argv": argv,
                "sh_c": sh_c,
                "cwd": cwd_o,
                "shell_session_id": sid_o,
                "intent": intent.strip()[:512],
                "timeout_sec": to_i,
            },
            None,
        )

    return None, "unsupported_action_id"


def create_approval_from_tool(*, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    action_id = arguments.get("action_id")
    if not isinstance(action_id, str) or action_id not in ALLOWED_APPROVAL_ACTION_IDS:
        return {
            "ok": False,
            "error": "action_id_not_allowed",
            "request_id": request_id,
            "allowed_action_ids": sorted(ALLOWED_APPROVAL_ACTION_IDS),
        }
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_must_be_object", "request_id": request_id}

    store_payload, err = validate_and_normalize_approval_payload(action_id, payload)
    if err or store_payload is None:
        return {"ok": False, "error": err or "invalid_payload", "request_id": request_id}

    flags = policy_flags_for_action(action_id)
    risk = risk_level_for_action(action_id)
    rec = create_pending(
        request_id=request_id,
        action_id=action_id,
        risk_level=risk,
        payload=store_payload,
        expires_at=None,
        tenant_id=resolve_tenant_id_for_store(),
        requires_double_confirmation=flags["requires_double_confirmation"],
        requires_confirmation=flags["requires_confirmation"],
    )
    write_orchestrator_audit(
        {
            "event": "approval_created_via_agent_tool",
            "approval_id": rec["approval_id"],
            "request_id": request_id,
            "action_id": action_id,
        }
    )
    return {"ok": True, "request_id": request_id, "approval": rec}


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_approvals = APIRouter()


def _dispatch_approved_job(rec: dict[str, Any], *, tenant_id: str) -> dict[str, Any] | None:
    if rec.get("status") != "approved":
        return None
    body = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    path = str(body.get("path") or "")
    if path:
        from app.shared.workspace_context import get_request_workspace_root
        from app.shared.workspace_guard import WorkspaceGuardError, resolve_workspace_path

        root = get_request_workspace_root()
        if root:
            try:
                resolve_workspace_path(workspace_root=root, path=path)
            except WorkspaceGuardError:
                return None
    job = maybe_enqueue_shell_job_after_approval(rec)
    if not job:
        from app.integrations.git_service import maybe_create_pr_after_approval, resolve_write_mode_for_path

        body = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        path = str(body.get("path") or "")
        if resolve_write_mode_for_path(path, tenant_id=tenant_id) == "pr_only":
            job = maybe_create_pr_after_approval(rec, tenant_id=tenant_id)
            if job and not job.get("ok"):
                from app.integrations.pr_failure import handle_pr_failure

                return handle_pr_failure(rec, job, tenant_id=tenant_id)
        if not job:
            if resolve_write_mode_for_path(path, tenant_id=tenant_id) == "pr_only":
                return {"ok": False, "mode": "pr_only", "error": "pr_only_no_local_write"}
            job = enqueue_file_job_after_approval(rec)
    return job


class ApprovalTestRequest(BaseModel):
    request_id: str | None = None
    action_id: str = "test.echo"
    risk_level: str = "P1"
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: str | None = None


@router_approvals.get("/approvals", tags=["WidgetMVP", "OpsDashboard"])
def approvals_list(
    status: str | None = Query(
        default="pending",
        description="pending = pendentes + aguardam 2ª confirmação (K.2); approved, denied ou all",
    ),
) -> dict[str, Any]:
    st: str | None = None if status == "all" else status
    tid = resolve_tenant_id_for_store()
    return {"items": list_approvals(st, tenant_id=tid)}


@router_approvals.get("/approvals/{approval_id}/diff", tags=["WidgetMVP"])
def approvals_diff(approval_id: str) -> dict[str, Any]:
    tid = resolve_tenant_id_for_store()
    rec = get_approval(approval_id, tenant_id=tid)
    if not rec:
        raise HTTPException(status_code=404, detail="approval_not_found")
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="diff_not_available")
    action_id = str(rec.get("action_id") or "")
    if action_id == "shell.exec":
        command = payload.get("preview") or payload.get("sh_c") or ""
        return {
            "approval_id": approval_id,
            "action_id": action_id,
            "status": rec.get("status"),
            "preview": str(command),
            "command": str(command),
            "cwd": payload.get("cwd"),
            "timeout_sec": payload.get("timeout_sec"),
            "kind": "shell",
        }
    diff = payload.get("diff")
    if not isinstance(diff, str):
        raise HTTPException(status_code=404, detail="diff_not_available")
    return {
        "approval_id": approval_id,
        "action_id": action_id,
        "status": rec.get("status"),
        "path": payload.get("path"),
        "summary": payload.get("summary"),
        "diff": diff,
    }


@router_approvals.post("/approvals/test", tags=["OpsDashboard"])
def approvals_test(payload: ApprovalTestRequest) -> dict[str, Any]:
    """Cria uma pendencia de teste (Fase B / DoD)."""
    rid = payload.request_id or str(uuid4())
    flags = policy_flags_for_action(payload.action_id)
    if payload.action_id in ALLOWED_APPROVAL_ACTION_IDS:
        if not isinstance(payload.payload, dict):
            raise HTTPException(status_code=400, detail="payload deve ser um objecto JSON.")
        store_payload, err = validate_and_normalize_approval_payload(
            payload.action_id, payload.payload
        )
        if err or store_payload is None:
            raise HTTPException(
                status_code=400,
                detail=f"Payload invalido para {payload.action_id} ({err}).",
            )
        risk = risk_level_for_action(payload.action_id)
    else:
        store_payload = dict(payload.payload)
        risk = payload.risk_level
    tid = resolve_tenant_id_for_store()
    rec = create_pending(
        request_id=rid,
        action_id=payload.action_id,
        risk_level=risk,
        payload=store_payload,
        expires_at=payload.expires_at,
        tenant_id=tid,
        requires_double_confirmation=flags["requires_double_confirmation"],
        requires_confirmation=flags["requires_confirmation"],
    )
    write_orchestrator_audit(
        {
            "event": "approval_created",
            "approval_id": rec["approval_id"],
            "request_id": rid,
            "action_id": payload.action_id,
            "tenant_id": tid,
        }
    )
    return rec


@router_approvals.post("/approvals/{approval_id}/approve", tags=["WidgetMVP", "OpsDashboard"])
def approvals_approve(approval_id: str) -> dict[str, Any]:
    tid = resolve_tenant_id_for_store()
    from app.shared.tenant_context import get_current_sub

    approver = get_current_sub()
    existing = get_approval(approval_id, tenant_id=tid)
    if not existing:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if CENTRAL_APPROVAL_SEPARATION:
        req = str(existing.get("requested_by_sub") or "").strip()
        if req and approver and req == approver.strip():
            raise HTTPException(status_code=403, detail="approval_separation_violation")
    mutation = approve_or_first_double_step(approval_id, tenant_id=tid, approver_sub=approver)
    if mutation is None:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada ou ja resolvida")
    if mutation.conflict:
        raise HTTPException(status_code=409, detail="approval_already_denied")
    rec = mutation.record
    if not mutation.changed:
        return {**rec, "idempotent_replay": True}
    resolution = (
        "awaiting_double_confirm"
        if rec.get("status") == "awaiting_double_confirm"
        else "approved"
    )
    write_orchestrator_audit(
        {
            "event": "approval_resolved" if resolution == "approved" else "approval_first_step",
            "approval_id": approval_id,
            "request_id": rec["request_id"],
            "resolution": resolution,
            "tenant_id": tid,
        }
    )
    try:
        from app.shared.business_metrics import inc_approval

        inc_approval(resolution)
    except Exception:
        pass
    job = _dispatch_approved_job(rec, tenant_id=tid)
    if job:
        rec = {**rec, "client_job": job, "client_job_id": job.get("job_id")}
        event = (
            "shell_exec_client_job_enqueued"
            if rec.get("action_id") == "shell.exec"
            else "file_client_job_enqueued"
        )
        if job.get("mode") == "pr_only":
            event = "github_pr_created" if job.get("provider") == "github" else "gitlab_mr_created"
        write_orchestrator_audit(
            {
                "event": event,
                "approval_id": approval_id,
                "request_id": rec["request_id"],
                "job_id": job.get("job_id"),
                "tenant_id": tid,
            }
        )
    from app.session_surface_service import clear_pending_approval, clear_pending_approval_by_approval_id

    sid = str(rec.get("session_id") or "").strip()
    if sid:
        clear_pending_approval(sid, tenant_id=tid)
    clear_pending_approval_by_approval_id(approval_id, tenant_id=tid)
    return rec


@router_approvals.post("/approvals/{approval_id}/confirm-double", tags=["WidgetMVP", "OpsDashboard"])
def approvals_confirm_double(approval_id: str) -> dict[str, Any]:
    """K.2 / H2 four-eyes: segundo aprovador distinto do primeiro."""
    tid = resolve_tenant_id_for_store()
    from app.shared.tenant_context import get_current_sub

    approver = get_current_sub()
    existing = get_approval(approval_id, tenant_id=tid)
    if existing and CENTRAL_APPROVAL_SEPARATION:
        req = str(existing.get("requested_by_sub") or "").strip()
        if req and approver and req == approver.strip():
            raise HTTPException(status_code=403, detail="approval_separation_violation")
    mutation = confirm_double(approval_id, tenant_id=tid, approver_sub=approver)
    if mutation is None:
        raise HTTPException(
            status_code=404,
            detail="Aprovacao nao esta a aguardar segunda confirmacao",
        )
    if mutation.conflict:
        raise HTTPException(status_code=409, detail="approval_double_confirm_conflict")
    rec = mutation.record
    if not mutation.changed:
        return {**rec, "idempotent_replay": True}
    write_orchestrator_audit(
        {
            "event": "approval_double_confirmed",
            "approval_id": approval_id,
            "request_id": rec["request_id"],
            "resolution": "approved",
            "tenant_id": tid,
        }
    )
    job = _dispatch_approved_job(rec, tenant_id=tid)
    if job:
        rec = {**rec, "client_job": job, "client_job_id": job.get("job_id")}
        event = "shell_exec_client_job_enqueued"
        if job.get("mode") == "pr_only":
            event = "github_pr_created" if job.get("provider") == "github" else "gitlab_mr_created"
        write_orchestrator_audit(
            {
                "event": event,
                "approval_id": approval_id,
                "request_id": rec["request_id"],
                "job_id": job.get("job_id"),
                "tenant_id": tid,
            }
        )
    return rec


class ApprovalDenyBody(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


@router_approvals.post("/approvals/{approval_id}/deny", tags=["WidgetMVP", "OpsDashboard"])
def approvals_deny(approval_id: str, body: ApprovalDenyBody | None = None) -> dict[str, Any]:
    tid = resolve_tenant_id_for_store()
    mutation = set_denied(approval_id, tenant_id=tid, reason=(body.reason if body else None))
    if mutation is None:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada ou ja resolvida")
    if mutation.conflict:
        raise HTTPException(status_code=409, detail="approval_already_approved")
    rec = mutation.record
    if not mutation.changed:
        return {**rec, "idempotent_replay": True}
    reason = (body.reason if body else None) or ""
    if reason.strip():
        try:
            from app.memory_service import propose_rule_from_rejection
            from app.shared.tenant_context import get_current_sub

            propose_rule_from_rejection(
                pattern=reason.strip(),
                tenant_id=tid,
                proposed_by=get_current_sub(),
                approval_id=approval_id,
                reason=reason.strip(),
                action_id=str(rec.get("action_id") or ""),
            )
        except Exception:
            pass
    work_item: dict[str, Any] | None = None
    try:
        from app.work_queue import maybe_create_work_item_from_denial
        from app.shared.tenant_context import get_current_sub

        work_item = maybe_create_work_item_from_denial(
            approval_id=approval_id,
            approval_rec=rec,
            reason=reason,
            tenant_id=tid,
            reporter_id=get_current_sub(),
        )
    except Exception:
        work_item = None
    audit_payload: dict[str, Any] = {
        "event": "approval_resolved",
        "approval_id": approval_id,
        "request_id": rec["request_id"],
        "resolution": "denied",
    }
    if work_item and work_item.get("id"):
        audit_payload["work_item_id"] = work_item["id"]
    write_orchestrator_audit(audit_payload)
    from app.session_surface_service import clear_pending_approval, clear_pending_approval_by_approval_id

    sid = str(rec.get("session_id") or "").strip()
    if sid:
        clear_pending_approval(sid, tenant_id=tid)
    clear_pending_approval_by_approval_id(approval_id, tenant_id=tid)
    out = dict(rec)
    if work_item:
        out["work_item"] = work_item
    return out
