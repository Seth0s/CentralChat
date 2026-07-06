"""Actions domain — system-agent action handlers, desktop/probe/shell execution.

Consolidated from:
  - desktop_actions.py       (URL/open/notify helpers)
  - probe_actions.py         (TCP/HTTP probe helpers)
  - request_shell_tool.py    (shell exec dispatch)
  - actions.py               (API router)
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.approvals import policy_flags_for_action, risk_level_for_action
from app.clients import (
    call_system_agent_firewall_policy_apply,
    call_system_agent_firewall_rule_apply,
    call_system_agent_process_signal,
    call_system_agent_read_external_file,
    call_system_agent_write_config_file,
    call_system_agent_mutate_external_path,
    call_system_agent_systemd_unit_disable_system,
    call_system_agent_systemd_unit_enable,
    call_system_agent_systemd_unit_restart,
    call_system_agent_systemd_unit_stop,
    call_system_agent_systemd_user_unit_disable,
    call_system_agent_os_power_reboot,
    call_system_agent_os_power_shutdown,
    call_system_agent_os_packages_install,
    call_system_agent_os_packages_upgrade_all,
    call_system_agent_os_account_unix_useradd,
)
from app.connector import (
    build_client_agent_offline_response,
    build_job_queued_shell_response,
    build_pending_hitl_shell_response,
    call_shell_gateway_run,
    classify_shell_request,
    connector_online_for_tenant,
    enqueue_shell_exec_client_job,
    maybe_enqueue_shell_job_after_approval,
    maybe_summarize_shell_output,
    tenant_shell_uses_client_connector,
)
from app.shared.approvals_store import create_pending, get_approval, resolve_tenant_id_for_store
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit
from typing import Literal

# ═══════════════════════════════════════════════════════════════════
# DESKTOP ACTIONS
# ═══════════════════════════════════════════════════════════════════

from app.config import (
    DESKTOP_HELPER_PATH,
    DESKTOP_HELPER_TIMEOUT_SEC,
    DESKTOP_NOTIFY_BODY_MAX,
    DESKTOP_NOTIFY_TITLE_MAX,
    OPEN_URL_ALLOW_HTTP,
    OPEN_URL_HOST_ALLOWLIST_RAW,
    OPEN_URL_MAX_LEN,
    PROBE_ALLOWLIST_RAW,
    PROBE_HTTP_PATH_ALLOWLIST_RAW,
    PROBE_TIMEOUT_SEC,
)


def open_url_host_allowlist_entries() -> list[str]:
    if not OPEN_URL_HOST_ALLOWLIST_RAW.strip():
        return []
    return [x.strip().lower() for x in OPEN_URL_HOST_ALLOWLIST_RAW.split(",") if x.strip()]


def hostname_matches_allowlist(hostname: str, entries: list[str]) -> bool:
    h = hostname.lower().rstrip(".")
    for e in entries:
        if not e:
            continue
        if e.startswith("."):
            suff = e[1:]
            if h == suff or h.endswith("." + suff):
                return True
        elif h == e:
            return True
    return False


def validate_open_url_for_queue(url: str) -> tuple[bool, str | None, str]:
    """
    Valida URL para criar pendencia desktop.open_url.
    Devolve (ok, codigo_erro_ou_none, url_normalizada).
    """
    s = url.strip()
    if not s or len(s) > OPEN_URL_MAX_LEN:
        return False, "invalid_url_length", ""
    if any(c in s for c in "\r\n\t\x00"):
        return False, "invalid_url_chars", ""
    parsed = urlparse(s)
    if parsed.username is not None or parsed.password is not None:
        return False, "url_userinfo_not_allowed", ""
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        pass
    elif scheme == "http":
        if not OPEN_URL_ALLOW_HTTP:
            return False, "http_scheme_not_allowed", ""
    else:
        return False, "url_scheme_not_allowed", ""
    host = parsed.hostname
    if not host:
        return False, "url_missing_host", ""
    entries = open_url_host_allowlist_entries()
    if not entries:
        return False, "open_url_allowlist_not_configured", ""
    if not hostname_matches_allowlist(host, entries):
        return False, "url_host_not_allowlisted", ""
    return True, None, s


def _sanitize_notify_line(s: str, max_len: int) -> tuple[bool, str]:
    t = s.strip()
    t = " ".join(t.split())
    if any(c in t for c in ("<", ">", "&", "`", "\x00")):
        return False, ""
    if len(t) > max_len or not t:
        return False, ""
    return True, t


def validate_notify_for_queue(body: str, title: str | None) -> tuple[bool, str | None, dict[str, Any]]:
    """
    Valida corpo/titulo para desktop.notify; devolve (ok, codigo_erro, payload_para_store).
    """
    ok_b, b = _sanitize_notify_line(body, DESKTOP_NOTIFY_BODY_MAX)
    if not ok_b:
        return False, "invalid_notify_body", {}
    store: dict[str, Any] = {"body": b, "urgency": "low"}
    if title is not None and str(title).strip():
        ok_t, t = _sanitize_notify_line(str(title), DESKTOP_NOTIFY_TITLE_MAX)
        if not ok_t:
            return False, "invalid_notify_title", {}
        store["title"] = t
    return True, None, store


def run_desktop_helper(op: str, envelope: dict[str, Any]) -> dict[str, Any]:
    """
    Invoca CENTRAL_DESKTOP_HELPER (ou legado SOPHIA_DESKTOP_HELPER) com JSON no stdin. Sem shell; timeout curto.
    """
    helper = DESKTOP_HELPER_PATH.strip()
    if not helper:
        return {
            "ok": False,
            "error": "desktop_helper_not_configured",
            "message_pt": (
                "O orquestrador nao tem CENTRAL_DESKTOP_HELPER definido (nem o legado SOPHIA_DESKTOP_HELPER). "
                "Configura no host o caminho para scripts/central-desktop-helper.sh (ou equivalente) "
                "para abrir URLs ou enviar notificacoes."
            ),
        }
    if not os.path.isfile(helper):
        return {
            "ok": False,
            "error": "desktop_helper_missing",
            "message_pt": "O ficheiro do helper de ambiente de trabalho nao existe (CENTRAL_DESKTOP_HELPER).",
        }
    payload = {"op": op, **envelope}
    raw = json.dumps(payload, ensure_ascii=False)
    cmd = [helper] if os.access(helper, os.X_OK) else ["/bin/bash", helper]
    try:
        proc = subprocess.run(
            cmd,
            input=raw.encode("utf-8"),
            capture_output=True,
            timeout=DESKTOP_HELPER_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "desktop_helper_timeout",
            "message_pt": "O helper de ambiente de trabalho excedeu o tempo limite.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "error": "desktop_helper_os_error",
            "message_pt": f"Nao foi possivel executar o helper: {exc}",
        }
    ok = proc.returncode == 0
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    return {
        "ok": ok,
        "returncode": proc.returncode,
        "stdout": out[:2048],
        "stderr": err[:2048],
        "message_pt": "Helper executado." if ok else "O helper devolveu erro (ver stderr no JSON).",
    }


# ═══════════════════════════════════════════════════════════════════
# PROBE ACTIONS
# ═══════════════════════════════════════════════════════════════════


def _default_http_paths() -> frozenset[str]:
    raw = PROBE_HTTP_PATH_ALLOWLIST_RAW.strip()
    if not raw:
        return frozenset({"/", "/health", "/-/healthy", "/-/ready"})
    paths = []
    for p in raw.split(","):
        s = p.strip()
        if not s:
            continue
        if not s.startswith("/"):
            s = "/" + s
        paths.append(s)
    return frozenset(paths) if paths else frozenset({"/"})


def parse_host_port_token(token: str) -> tuple[str, int] | None:
    """Interpreta um token host:port da allowlist (IPv4 ou hostname; IPv6 entre [])."""
    s = token.strip()
    if not s:
        return None
    if s.startswith("["):
        end = s.find("]:")
        if end == -1:
            return None
        host = s[1:end].strip()
        port_s = s[end + 2 :].strip()
    else:
        if ":" not in s:
            return None
        host, port_s = s.rsplit(":", 1)
        host = host.strip()
        port_s = port_s.strip()
    if not host or not port_s:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    if port < 1 or port > 65535:
        return None
    if len(host) > 253 or "\x00" in host:
        return None
    return host, port


def probe_allowlist_endpoints() -> frozenset[tuple[str, int]]:
    """Conjunto (host_lower, port) para comparação; IPv6 guardado em minúsculas estável."""
    out: set[tuple[str, int]] = set()
    for part in PROBE_ALLOWLIST_RAW.split(","):
        ep = parse_host_port_token(part)
        if ep:
            h, p = ep
            out.add((h.lower(), p))
    return frozenset(out)


def endpoint_allowed(host: str, port: int) -> bool:
    allow = probe_allowlist_endpoints()
    if not allow:
        return False
    return (host.strip().lower(), int(port)) in allow


def validate_probe_for_queue(
    host: str,
    port: Any,
    kind: Any,
    path: Any,
) -> tuple[bool, str | None, dict[str, Any]]:
    """
    Valida pedido para network.endpoint.probe.
    Devolve (ok, codigo_erro, store_payload).
    """
    allow = probe_allowlist_endpoints()
    if not allow:
        return False, "probe_allowlist_not_configured", {}

    if not isinstance(host, str) or not host.strip():
        return False, "invalid_probe_host", {}
    h = host.strip()
    if len(h) > 253 or "\x00" in h or any(c in h for c in " \t\r\n"):
        return False, "invalid_probe_host", {}

    if isinstance(port, bool) or not isinstance(port, int):
        return False, "invalid_probe_port", {}
    if port < 1 or port > 65535:
        return False, "invalid_probe_port", {}

    if not isinstance(kind, str) or not kind.strip():
        return False, "invalid_probe_kind", {}
    k = kind.strip().lower()
    if k not in ("tcp", "http"):
        return False, "invalid_probe_kind", {}

    http_paths = _default_http_paths()
    path_out: str | None = None
    if k == "tcp":
        if path is not None and path != "":
            return False, "probe_path_not_allowed_for_tcp", {}
    else:
        if path is None or path == "":
            path_out = "/"
        elif isinstance(path, str):
            p = path.strip()
            if not p.startswith("/"):
                p = "/" + p
            if p not in http_paths:
                return False, "probe_http_path_not_allowlisted", {}
            path_out = p
        else:
            return False, "invalid_probe_path", {}

    if not endpoint_allowed(h, port):
        return False, "probe_endpoint_not_allowlisted", {}

    store: dict[str, Any] = {"host": h, "port": port, "kind": k}
    if k == "http" and path_out is not None:
        store["path"] = path_out
    return True, None, store


def run_network_probe(store_payload: dict[str, Any]) -> dict[str, Any]:
    """Executa sondagem após aprovação (revalida allowlist)."""
    h = store_payload.get("host")
    p = store_payload.get("port")
    k = store_payload.get("kind")
    path = store_payload.get("path", "/")
    if not isinstance(h, str) or not isinstance(p, int) or not isinstance(k, str):
        return {"ok": False, "error": "invalid_stored_payload", "message_pt": "Payload da sondagem inválido."}
    ok, err, _norm = validate_probe_for_queue(h, p, k, path if k == "http" else None)
    if not ok:
        return {
            "ok": False,
            "error": err or "validation_failed",
            "message_pt": "O endpoint deixou de ser válido ou não está na allowlist.",
        }
    timeout = PROBE_TIMEOUT_SEC
    if k == "tcp":
        try:
            with socket.create_connection((h, p), timeout=timeout):
                pass
        except OSError as exc:
            return {
                "ok": True,
                "probe_ok": False,
                "kind": "tcp",
                "host": h,
                "port": p,
                "error": str(exc),
                "message_pt": "Ligação TCP falhou.",
            }
        return {
            "ok": True,
            "probe_ok": True,
            "kind": "tcp",
            "host": h,
            "port": p,
            "message_pt": "Ligação TCP estabelecida.",
        }

    safe_path = path if isinstance(path, str) and path.startswith("/") else "/"
    host_bracket = f"[{h}]" if ":" in h else h
    url = f"http://{host_bracket}:{p}{safe_path}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(url)
        return {
            "ok": True,
            "probe_ok": 200 <= response.status_code < 400,
            "kind": "http",
            "host": h,
            "port": p,
            "path": safe_path,
            "http_status": response.status_code,
            "message_pt": f"HTTP respondeu com código {response.status_code}.",
        }
    except httpx.HTTPError as exc:
        return {
            "ok": True,
            "probe_ok": False,
            "kind": "http",
            "host": h,
            "port": p,
            "path": safe_path,
            "error": str(exc),
            "message_pt": "Pedido HTTP falhou (timeout ou erro de rede).",
        }


# ═══════════════════════════════════════════════════════════════════
# REQUEST SHELL
# ═══════════════════════════════════════════════════════════════════


def finalize_shell_gateway_dict(
    gw: dict[str, Any],
    *,
    request_id: str,
    audit_event: str,
) -> dict[str, Any]:
    """Normaliza resposta HTTP do gateway (apos run) com resumo opcional + audit."""
    if gw.get("ok") is False or (gw.get("error") is not None and "exit_code" not in gw):
        return {
            "ok": False,
            "error": gw.get("error", "shell_failed"),
            "request_id": request_id,
        }
    truncated = bool(gw.get("truncated"))
    stdout = str(gw.get("stdout", ""))
    stderr = str(gw.get("stderr", ""))
    merged = maybe_summarize_shell_output(stdout=stdout, stderr=stderr, truncated=truncated)
    write_orchestrator_audit(
        {
            "event": audit_event,
            "request_id": request_id,
            "exit_code": gw.get("exit_code"),
            "summary_applied": merged.get("summary_applied"),
        }
    )
    out: dict[str, Any] = {
        "ok": True,
        "exit_code": gw.get("exit_code"),
        "stdout": merged["stdout"],
        "stderr": merged["stderr"],
        "truncated": truncated,
        "timed_out": bool(gw.get("timed_out")),
        "request_id": request_id,
    }
    if merged.get("summary_applied"):
        out["shell_output_summary_pt"] = merged.get("shell_output_summary_pt", "")
    return out


def execute_shell_exec_payload(*, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    """
    Executa shell.exec aprovado.

    Legacy (``CENTRAL_LEGACY_PLATFORM_TOOLS=1``): shell-gateway na VPS.
    Tenant path: enfileira ``client_job`` para o connector.
    """
    body = dict(payload)
    if tenant_shell_uses_client_connector():
        tid = resolve_tenant_id_for_store()
        if not connector_online_for_tenant(tenant_id=tid):
            return build_client_agent_offline_response(request_id=request_id)
        job = enqueue_shell_exec_client_job(
            tenant_id=tid,
            payload=body,
            request_id=request_id,
        )
        write_orchestrator_audit(
            {
                "event": "shell_exec_client_job_enqueued",
                "request_id": request_id,
                "job_id": job.get("job_id"),
            }
        )
        return build_job_queued_shell_response(
            job=job,
            request_id=request_id,
            classification="approved_enqueue",
        )
    gw = call_shell_gateway_run(body, request_id)
    return finalize_shell_gateway_dict(gw, request_id=request_id, audit_event="shell_exec_action_done")


def _session_id_from_ctx(ctx: dict[str, Any] | None) -> str | None:
    if not ctx:
        return None
    sid = str(ctx.get("chat_session_id") or "").strip()
    return sid if len(sid) >= 8 else None


def dispatch_request_shell(
    *,
    arguments: dict[str, Any],
    request_id: str,
    canvas_write_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = str(arguments.get("mode", "")).strip()
    argv = arguments.get("argv")
    if argv is not None and not isinstance(argv, list):
        argv = None
    else:
        argv = [str(x) for x in argv] if argv else None
    sh_c = arguments.get("sh_c")
    if sh_c is not None and not isinstance(sh_c, str):
        sh_c = None
    cwd = arguments.get("cwd")
    cwd_s = str(cwd).strip() if isinstance(cwd, str) else None
    sid = arguments.get("shell_session_id")
    sid_s = str(sid).strip() if isinstance(sid, str) else None
    intent = str(arguments.get("intent", "")).strip()
    if not intent:
        return {"ok": False, "error": "intent_required", "request_id": request_id}
    to = arguments.get("timeout_sec")
    to_i = int(to) if isinstance(to, int) else None

    clf, verr = classify_shell_request(
        mode=mode,
        argv=argv,
        sh_c=sh_c,
        cwd=cwd_s,
        shell_session_id=sid_s,
        intent=intent,
        timeout_sec=to_i,
        request_id=request_id,
    )
    if verr or clf is None:
        return {"ok": False, "error": verr or "classify_failed", "request_id": request_id}

    body = dict(clf.gateway_body)
    body["cwd"] = clf.normalized_cwd
    tid = resolve_tenant_id_for_store()
    use_client = tenant_shell_uses_client_connector()
    chat_session_id = _session_id_from_ctx(canvas_write_ctx)

    if clf.risk == "P3":
        action_id = "shell.exec"
        flags = policy_flags_for_action(action_id)
        risk = risk_level_for_action(action_id)
        rec = create_pending(
            request_id=request_id,
            action_id=action_id,
            risk_level=risk,
            payload=body,
            tenant_id=tid,
            requires_double_confirmation=flags["requires_double_confirmation"],
            requires_confirmation=flags["requires_confirmation"],
            session_id=chat_session_id,
        )
        write_orchestrator_audit(
            {
                "event": "approval_created_request_shell",
                "approval_id": rec["approval_id"],
                "request_id": request_id,
                "action_id": action_id,
                "reason": clf.reason,
                "tenant_id": tid,
            }
        )
        return build_pending_hitl_shell_response(
            rec=rec,
            request_id=request_id,
            classification=clf.reason,
        )

    if use_client:
        if not connector_online_for_tenant(tenant_id=tid):
            return build_client_agent_offline_response(
                request_id=request_id,
                classification=clf.reason,
            )
        job = enqueue_shell_exec_client_job(
            tenant_id=tid,
            payload=body,
            request_id=request_id,
            session_id=chat_session_id,
        )
        write_orchestrator_audit(
            {
                "event": "request_shell_p0_client_job",
                "request_id": request_id,
                "job_id": job.get("job_id"),
                "reason": clf.reason,
            }
        )
        return build_job_queued_shell_response(
            job=job,
            request_id=request_id,
            classification=clf.reason,
        )

    gw = call_shell_gateway_run(body, request_id)
    fin = finalize_shell_gateway_dict(gw, request_id=request_id, audit_event="request_shell_p0_done")
    if not fin.get("ok"):
        return {**fin, "classification": clf.reason}
    fin["status"] = "executed"
    fin["classification"] = clf.reason
    return fin


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_actions = APIRouter()


class ProcessSignalActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    pid: int = Field(..., gt=1)
    signal: int | None = Field(default=None, description="Opcional; defeito SIGTERM (15). Apenas SIGTERM suportado na Fase C.")


class SystemdRestartActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)


class SystemdStopActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)


class SystemdUserUnitDisableActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)


class SystemdUnitEnableActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)


class SystemdUnitDisableSystemActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)


class OsAccountUnixUseraddActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1, max_length=32)


class OsPowerActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)


class DesktopOpenUrlActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1, max_length=2048)


class DesktopNotifyActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, max_length=512)
    title: str | None = Field(default=None, max_length=128)


class ReadExternalFileActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1, max_length=4096)
    max_bytes: int | None = Field(default=None, ge=256, le=65536, description="Opcional; defeito 16384 no system-agent")


class ShellExecActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)


class WriteConfigFileActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1, max_length=4096)
    content: str = Field(default="", max_length=32768)
    create_backup: bool = Field(default=True)


class MutateExternalPathActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    operation: Literal["copy", "move", "delete"] = Field(...)
    src_path: str = Field(..., min_length=1, max_length=4096)
    dst_path: str | None = Field(default=None, max_length=4096, description="Obrigatorio para copy/move; omitir ou vazio para delete")


class FirewallRuleApplyActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = Field(...)
    direction: Literal["in", "out"] = Field(...)
    action: Literal["allow", "deny"] = Field(...)


class FirewallPolicyActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    operation: Literal["reload", "set_default_zone"] = Field(...)
    zone: str | None = Field(default=None, max_length=32)


class OsPackagesInstallActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    package: str = Field(..., min_length=1, max_length=200)


class OsPackagesUpgradeAllActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)


class NetworkProbeActionRequest(BaseModel):
    request_id: str | None = None
    approval_id: str = Field(..., min_length=1)
    host: str = Field(..., min_length=1, max_length=253)


# ── Routes ──

@router_actions.post("/actions/process-signal", tags=["OpsDashboard"])
def action_process_signal(payload: ProcessSignalActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "process.signal":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para process.signal")
    payload_pid = rec.get("payload", {}).get("pid")
    if payload_pid is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir pid")
    if int(payload_pid) != payload.pid:
        raise HTTPException(status_code=403, detail="pid nao coincide com payload da aprovacao")
    sig = payload.signal if payload.signal is not None else int(signal.SIGTERM)
    if sig != int(signal.SIGTERM):
        raise HTTPException(status_code=400, detail="apenas SIGTERM suportado na Fase C")
    try:
        result = call_system_agent_process_signal(
            rid, payload.pid, sig, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            detail = body.get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p1_process_signal_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "process.signal", "pid": payload.pid, "result_ok": True})
    return result


@router_actions.post("/actions/systemd-restart", tags=["OpsDashboard"])
def action_systemd_restart(payload: SystemdRestartActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "systemd.unit.restart":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para systemd.unit.restart")
    payload_unit = rec.get("payload", {}).get("unit")
    if payload_unit is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir unit")
    if str(payload_unit).strip() != payload.unit.strip():
        raise HTTPException(status_code=403, detail="unit nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_systemd_unit_restart(
            rid, payload.unit.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_systemd_restart_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "systemd.unit.restart", "unit": payload.unit.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/systemd-stop", tags=["OpsDashboard"])
def action_systemd_stop(payload: SystemdStopActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "systemd.unit.stop":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para systemd.unit.stop")
    payload_unit = rec.get("payload", {}).get("unit")
    if payload_unit is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir unit")
    if str(payload_unit).strip() != payload.unit.strip():
        raise HTTPException(status_code=403, detail="unit nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_systemd_unit_stop(
            rid, payload.unit.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_systemd_stop_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "systemd.unit.stop", "unit": payload.unit.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/systemd-user-unit-disable", tags=["OpsDashboard"])
def action_systemd_user_unit_disable(payload: SystemdUserUnitDisableActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "systemd.user.unit.disable":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para systemd.user.unit.disable")
    payload_unit = rec.get("payload", {}).get("unit")
    if payload_unit is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir unit")
    if str(payload_unit).strip() != payload.unit.strip():
        raise HTTPException(status_code=403, detail="unit nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_systemd_user_unit_disable(
            rid, payload.unit.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_systemd_user_unit_disable_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "systemd.user.unit.disable", "unit": payload.unit.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/systemd-unit-enable", tags=["OpsDashboard"])
def action_systemd_unit_enable(payload: SystemdUnitEnableActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "systemd.unit.enable":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para systemd.unit.enable")
    payload_unit = rec.get("payload", {}).get("unit")
    if payload_unit is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir unit")
    if str(payload_unit).strip() != payload.unit.strip():
        raise HTTPException(status_code=403, detail="unit nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_systemd_unit_enable(
            rid, payload.unit.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_systemd_unit_enable_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "systemd.unit.enable", "unit": payload.unit.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/systemd-unit-disable-system", tags=["OpsDashboard"])
def action_systemd_unit_disable_system(payload: SystemdUnitDisableSystemActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "systemd.unit.disable":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para systemd.unit.disable")
    payload_unit = rec.get("payload", {}).get("unit")
    if payload_unit is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir unit")
    if str(payload_unit).strip() != payload.unit.strip():
        raise HTTPException(status_code=403, detail="unit nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_systemd_unit_disable_system(
            rid, payload.unit.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_systemd_unit_disable_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "systemd.unit.disable", "unit": payload.unit.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/os-account-unix-useradd", tags=["OpsDashboard"])
def action_os_account_unix_useradd(payload: OsAccountUnixUseraddActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "os.account.unix_useradd":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para os.account.unix_useradd")
    payload_user = rec.get("payload", {}).get("username")
    if payload_user is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir username")
    if str(payload_user).strip() != payload.username.strip():
        raise HTTPException(status_code=403, detail="username nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_os_account_unix_useradd(
            rid, payload.username.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_os_account_unix_useradd_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "os.account.unix_useradd", "username": payload.username.strip(), "result_ok": True})
    return result


@router_actions.post("/actions/os-power-reboot", tags=["OpsDashboard"])
def action_os_power_reboot(payload: OsPowerActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "os.power.reboot":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para os.power.reboot")
    try:
        result = call_system_agent_os_power_reboot(
            rid, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_os_power_reboot_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "os.power.reboot", "result_ok": True})
    return result


@router_actions.post("/actions/os-power-shutdown", tags=["OpsDashboard"])
def action_os_power_shutdown(payload: OsPowerActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "os.power.shutdown":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para os.power.shutdown")
    try:
        result = call_system_agent_os_power_shutdown(
            rid, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_os_power_shutdown_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "os.power.shutdown", "result_ok": True})
    return result


@router_actions.post("/actions/desktop-open-url", tags=["OpsDashboard"])
def action_desktop_open_url(payload: DesktopOpenUrlActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "desktop.open_url":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para desktop.open_url")
    payload_url = rec.get("payload", {}).get("url")
    if payload_url is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir url")
    if str(payload_url).strip() != payload.url.strip():
        raise HTTPException(status_code=403, detail="url nao coincide com payload da aprovacao")
    result = run_desktop_helper("open_url", {"url": payload.url.strip()})
    write_orchestrator_audit({"event": "p1_desktop_open_url_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "desktop.open_url", "url": payload.url.strip(), "result_ok": result.get("ok")})
    return result


@router_actions.post("/actions/desktop-notify", tags=["OpsDashboard"])
def action_desktop_notify(payload: DesktopNotifyActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "desktop.notify":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para desktop.notify")
    payload_body = rec.get("payload", {}).get("body")
    if payload_body is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir body")
    envelope = {"body": payload.body.strip()}
    if payload.title:
        envelope["title"] = payload.title.strip()
    result = run_desktop_helper("notify", envelope)
    write_orchestrator_audit({"event": "p1_desktop_notify_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "desktop.notify", "result_ok": result.get("ok")})
    return result


@router_actions.post("/actions/network-probe", tags=["OpsDashboard"])
def action_network_probe(payload: NetworkProbeActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "network.endpoint.probe":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para network.endpoint.probe")
    store_payload = rec.get("payload")
    if not isinstance(store_payload, dict):
        raise HTTPException(status_code=403, detail="payload da aprovacao invalido")
    h = store_payload.get("host")
    if not h or str(h).strip() != payload.host.strip():
        raise HTTPException(status_code=403, detail="host nao coincide com payload da aprovacao")
    result = run_network_probe(store_payload)
    write_orchestrator_audit({"event": "p1_network_probe_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "network.endpoint.probe", "result_ok": result.get("ok")})
    return result


@router_actions.post("/actions/read-external-file", tags=["OpsDashboard"])
def action_read_external_file(payload: ReadExternalFileActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "filesystem.path.read_external":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para filesystem.path.read_external")
    payload_path = rec.get("payload", {}).get("path")
    if payload_path is None:
        raise HTTPException(status_code=403, detail="payload da aprovacao deve incluir path")
    if str(payload_path).strip() != payload.path.strip():
        raise HTTPException(status_code=403, detail="path nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_read_external_file(rid, payload.path.strip(), payload.approval_id, max_bytes=payload.max_bytes)
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p1_read_external_file_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "filesystem.path.read_external", "result_ok": True})
    return result


@router_actions.post("/actions/write-config-file", tags=["OpsDashboard"])
def action_write_config_file(payload: WriteConfigFileActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "filesystem.path.write_config":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para filesystem.path.write_config")
    sp = rec.get("payload", {})
    if str(sp.get("path", "")).strip() != payload.path.strip():
        raise HTTPException(status_code=403, detail="path nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_write_config_file(rid, payload.path.strip(), payload.content, payload.create_backup, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_write_config_file_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "filesystem.path.write_config", "result_ok": True})
    return result


@router_actions.post("/actions/mutate-external-path", tags=["OpsDashboard"])
def action_mutate_external_path(payload: MutateExternalPathActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "filesystem.path.mutate_external":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para filesystem.path.mutate_external")
    sp = rec.get("payload", {})
    if str(sp.get("src_path", "")).strip() != payload.src_path.strip():
        raise HTTPException(status_code=403, detail="src_path nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_mutate_external_path(rid, payload.operation, payload.src_path.strip(), payload.dst_path.strip() if payload.dst_path else None, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_mutate_external_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "filesystem.path.mutate_external", "result_ok": True})
    return result


@router_actions.post("/actions/firewall-rule-apply", tags=["OpsDashboard"])
def action_firewall_rule_apply(payload: FirewallRuleApplyActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "network.firewall.rule.apply":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para network.firewall.rule.apply")
    sp = rec.get("payload", {})
    if int(sp.get("port", 0)) != payload.port:
        raise HTTPException(status_code=403, detail="port nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_firewall_rule_apply(rid, payload.port, payload.protocol, payload.direction, payload.action, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_firewall_rule_apply_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "network.firewall.rule.apply", "result_ok": True})
    return result


@router_actions.post("/actions/firewall-policy-apply", tags=["OpsDashboard"])
def action_firewall_policy_apply(payload: FirewallPolicyActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "network.firewall.policy.apply":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para network.firewall.policy.apply")
    try:
        result = call_system_agent_firewall_policy_apply(rid, payload.operation, payload.zone, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_firewall_policy_apply_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "network.firewall.policy.apply", "result_ok": True})
    return result


@router_actions.post("/actions/os-packages-install", tags=["OpsDashboard"])
def action_os_packages_install(payload: OsPackagesInstallActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "os.packages.install":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para os.packages.install")
    sp = rec.get("payload", {})
    if str(sp.get("package", "")).strip() != payload.package.strip():
        raise HTTPException(status_code=403, detail="package nao coincide com payload da aprovacao")
    try:
        result = call_system_agent_os_packages_install(rid, payload.package.strip(), payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p2_os_packages_install_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "os.packages.install", "result_ok": True})
    return result


@router_actions.post("/actions/os-packages-upgrade-all", tags=["OpsDashboard"])
def action_os_packages_upgrade_all(payload: OsPackagesUpgradeAllActionRequest) -> dict[str, Any]:
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "os.packages.upgrade_all":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para os.packages.upgrade_all")
    try:
        result = call_system_agent_os_packages_upgrade_all(rid, payload.approval_id,
            double_confirmation_ack=bool(rec.get("requires_double_confirmation")),
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.text else {}
        detail = body.get("detail", exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail=str(detail)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar system-agent: {exc}") from exc
    write_orchestrator_audit({"event": "p3_os_packages_upgrade_all_done", "request_id": rid, "approval_id": payload.approval_id, "action_id": "os.packages.upgrade_all", "result_ok": True})
    return result


@router_actions.post("/actions/shell-exec", tags=["OpsDashboard"])
def action_shell_exec(payload: ShellExecActionRequest) -> dict[str, Any]:
    """Executa shell.exec aprovado: payload lido da fila de aprovacoes."""
    rid = payload.request_id or str(uuid4())
    rec = get_approval(payload.approval_id, tenant_id=resolve_tenant_id_for_store())
    if not rec:
        raise HTTPException(status_code=404, detail="Aprovacao nao encontrada")
    if rec.get("status") not in ("approved", "awaiting_double_confirm"):
        raise HTTPException(status_code=403, detail="Aprovacao deve estar approved")
    if rec.get("action_id") != "shell.exec":
        raise HTTPException(status_code=403, detail="Aprovacao nao e para shell.exec")
    store_payload = rec.get("payload")
    if not isinstance(store_payload, dict):
        raise HTTPException(status_code=403, detail="payload da aprovacao invalido")
    return execute_shell_exec_payload(payload=store_payload, request_id=rid)
