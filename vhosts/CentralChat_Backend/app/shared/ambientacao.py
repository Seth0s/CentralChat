
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.approvals import APPROVAL_QUEUE_ACTION_IDS, P2_RESERVED_ACTION_IDS

_APPROVAL_CREATE = "orchestrator.approval.create"


# Canonical pre-injection (English for maximum model clarity). Align with docs/guides/ambientacao-pre-pos-injecao.md.
# Legacy name kept for imports and docs that reference `CANONICAL_PRE_INJECTION_PT`.
CANONICAL_PRE_INJECTION = """\
[SYSTEM]
[SYS_ENV]
ID: Central
User: Lucas
Privilege: user
OS: {os.type()} ({os.release()})
"""

CANONICAL_PRE_INJECTION_PT = CANONICAL_PRE_INJECTION


def load_pre_injection_from_file(path: str) -> str | None:
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def get_pre_injection_body(*, file_path: str | None) -> str:
    if file_path:
        custom = load_pre_injection_from_file(file_path)
        if custom:
            return custom
    return CANONICAL_PRE_INJECTION


def build_pre_injection_message(content: str) -> dict[str, str] | None:
    c = content.strip()
    if not c:
        return None
    return {"role": "system", "content": c}


def build_capability_digest_system_message(*, max_chars: int = 2600) -> dict[str, str] | None:
    """
    System message with the L0-2 digest (same idea as `capability_digest_preview` on /config).
    Use only when `CAPABILITY_DIGEST_IN_PROMPT_ENABLED` and the request or L2 opts in.
    """
    body = build_capability_digest_pt_br(max_chars=max_chars).strip()
    if not body:
        return None
    return {"role": "system", "content": body}


def _capability_digest_line(entry: dict[str, Any]) -> str:
    name = str(entry["name"])
    risk = str(entry["risk_level"])
    aid = str(entry["maps_to_action_id"])
    if aid == _APPROVAL_CREATE:
        if name == "create_approval_request":
            note = "meta-tool: enqueues typed payloads; does not execute on host"
        else:
            note = "creates HITL queue item; host execution only after UI approval"
    else:
        note = "read-only query via system-agent (policy + allowlists)"
    return f"- `{name}` → `{aid}` ({risk}) — {note}"


def build_capability_digest_pt_br(*, max_chars: int = 2800) -> str:
    """
    Capability digest (English) from the tool catalog + HITL queue (wave L0-2).
    Kept name `build_capability_digest_pt_br` for import compatibility; body is English for model clarity.
    """
    from app.tools import get_agent_tools_catalog
    rows = sorted(get_agent_tools_catalog(), key=lambda e: (e["risk_level"], e["name"]))
    risk_order = ("P0", "P1", "P2", "P3")
    by_risk: dict[str, list[dict[str, Any]]] = {}
    for e in rows:
        rl = str(e.get("risk_level") or "P0")
        by_risk.setdefault(rl, []).append(e)
    ordered_risks = [k for k in risk_order if by_risk.get(k)] + [
        k for k in sorted(by_risk.keys()) if k not in risk_order
    ]

    lines: list[str] = [
        "[CAPABILITY_DIGEST — Central agent tools; built at runtime from tool_registry + action_policy]",
        "",
        "Summary: P0 tools are immediate read/query. Tools mapping to "
        f"`{_APPROVAL_CREATE}` only create queue items — host execution depends on the queue and policy.",
        "",
    ]
    for rk in ordered_risks:
        bucket = by_risk.get(rk) or []
        if not bucket:
            continue
        lines.append(f"## {rk}")
        for e in bucket:
            lines.append(_capability_digest_line(e))
        lines.append("")

    aq = ", ".join(sorted(APPROVAL_QUEUE_ACTION_IDS))
    lines.append("## HITL queue (action_id known to the orchestrator)")
    lines.append(
        "These `action_id` values typically require human approval before system-agent / host execution: "
        f"{aq}."
    )
    if P2_RESERVED_ACTION_IDS:
        lines.append(
            "Reserved / roadmap (policy may still deny): "
            + ", ".join(sorted(P2_RESERVED_ACTION_IDS))
            + "."
        )
    lines.append("")
    lines.append(
        "Source of truth: `tool_registry._TOOL_SPECS`, `action_policy.APPROVAL_QUEUE_ACTION_IDS`, "
        "guide `docs/guides/agent-tools-inventory.md`."
    )

    body = "\n".join(lines).strip()
    suffix = "\n… (truncated)"
    if len(body) <= max_chars:
        return body
    return body[: max(0, max_chars - len(suffix))].rstrip() + suffix


def _format_byte_count(n: int) -> str:
    gib = 1024**3
    mib = 1024**2
    if n >= gib:
        return f"{n / gib:.2f} GiB"
    if n >= mib:
        return f"{n / mib:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_host_context_block(host_payload: dict[str, Any], *, max_chars: int = 6000) -> str:
    """
    Turn the best-effort aggregate (system-agent + kernel-observer + optional auditd sample K.5) into prompt lines.
    Avoids raw JSON in the system message (fewer tokens, clearer for the model).

    ADR-017: describes the **Central deploy host (VPS)**, not the end-user PC (use connector tools for that).
    """
    lines: list[str] = [
        "[HOST_CONTEXT — Central server / VPS (not the tenant device); enable CENTRAL_INCLUDE_PLATFORM_CONTEXT or legacy mode]",
    ]

    rid = host_payload.get("request_id")
    if rid is not None:
        lines.append(f"request_id: {rid}")

    sa = host_payload.get("system_agent")
    if isinstance(sa, dict) and sa.get("error"):
        lines.append("system_agent: unavailable")
        lines.append(f"  error: {sa['error']}")
    elif isinstance(sa, dict):
        lines.append("system_agent (system.summary):")
        data = sa.get("data")
        if isinstance(data, dict):
            cpu = data.get("cpu_percent")
            if cpu is not None:
                lines.append(f"  cpu_percent: {cpu}")
            mt = _as_int(data.get("mem_total_bytes"))
            mu = _as_int(data.get("mem_used_bytes"))
            if mt is not None and mu is not None:
                lines.append(f"  memory: {_format_byte_count(mu)} used of {_format_byte_count(mt)}")
            dt = _as_int(data.get("disk_total_bytes"))
            du = _as_int(data.get("disk_used_bytes"))
            if dt is not None and du is not None:
                lines.append(f"  disk_root: {_format_byte_count(du)} used of {_format_byte_count(dt)}")
            up = _as_int(data.get("uptime_seconds"))
            if up is not None:
                lines.append(f"  uptime_s: {up}")
            la = data.get("load_average")
            if isinstance(la, dict) and la:
                l1, l5, l15 = la.get("1m"), la.get("5m"), la.get("15m")
                if l1 is not None or l5 is not None or l15 is not None:
                    lines.append(f"  loadavg_1m_5m_15m: {l1},{l5},{l15}")
            osb = data.get("os")
            if isinstance(osb, dict):
                pretty = osb.get("pretty_name") or osb.get("system")
                if pretty:
                    lines.append(f"  OS: {pretty}")
                if osb.get("release"):
                    lines.append(f"  kernel_release: {osb['release']}")
                cl = osb.get("container_likely")
                if cl is not None:
                    lines.append(f"  container_likely: {cl}")
            art = data.get("agent_runtime")
            if isinstance(art, dict):
                impl = art.get("implementation")
                pyv = art.get("python")
                if impl or pyv:
                    lines.append(f"  agent_runtime: {impl or '?'} Python {pyv or '?'}")
        else:
            lines.append("  (no data field; unexpected response)")
    else:
        lines.append("system_agent: (unexpected response)")

    ko_err = host_payload.get("kernel_observer_error")
    ko = host_payload.get("kernel_observer")
    if ko_err:
        lines.append("kernel_observer: unavailable")
        lines.append(f"  error: {ko_err}")
    elif isinstance(ko, dict):
        lines.append("kernel_observer (snapshot):")
        if ko.get("cpu_percent") is not None:
            lines.append(f"  cpu_percent: {ko['cpu_percent']}")
        mem = ko.get("memory")
        if isinstance(mem, dict):
            tot = _as_int(mem.get("total"))
            av = _as_int(mem.get("available"))
            pct = mem.get("percent")
            parts: list[str] = []
            if av is not None and tot is not None:
                parts.append(f"available {_format_byte_count(av)} of {_format_byte_count(tot)}")
            if pct is not None:
                parts.append(f"usage_approx {pct}%")
            if parts:
                lines.append(f"  memory: {', '.join(parts)}")
        la = ko.get("loadavg")
        if isinstance(la, dict) and any(v is not None for v in (la.get("1m"), la.get("5m"), la.get("15m"))):
            lines.append(
                f"  loadavg_1m_5m_15m: {la.get('1m')}, {la.get('5m')}, {la.get('15m')}"
            )
    else:
        lines.append("kernel_observer: no data")

    ka_err = host_payload.get("kernel_audit_error")
    ka = host_payload.get("kernel_audit")
    if ka_err:
        lines.append("kernel_audit (audit.log sample): unavailable")
        lines.append(f"  error: {ka_err}")
    elif isinstance(ka, dict):
        if ka.get("enabled") is False:
            lines.append("kernel_audit: auditd sample disabled (no AUDIT_LOG_PATH on observer)")
        elif not ka.get("readable"):
            err = ka.get("error") or "not readable"
            lines.append(f"kernel_audit: sample not readable ({err})")
        else:
            tc = ka.get("type_counts")
            if isinstance(tc, dict) and tc:
                top = sorted(tc.items(), key=lambda x: -x[1])[:8]
                parts = [f"{k}={v}" for k, v in top]
                more = f" (+{len(tc) - len(top)} types)" if len(tc) > len(top) else ""
                lines.append(f"kernel_audit (type_counts in sample): {', '.join(parts)}{more}")
                li = ka.get("lines_in_sample")
                if li is not None:
                    lines.append(f"  lines_in_sample: {li}")
            else:
                lines.append("kernel_audit: empty sample or no recognized type=")

    body = "\n".join(lines)
    suffix = "\n… (truncated)"
    if len(body) <= max_chars:
        return body
    return body[: max(0, max_chars - len(suffix))].rstrip() + suffix


def format_host_context_for_prompt(host_payload: dict[str, Any], *, max_chars: int = 6000) -> str:
    """Post-injection: safe text block (no credentials) derived from the host aggregate."""
    block = build_host_context_block(host_payload, max_chars=max_chars)
    return (
        "[FACTUAL_HOST_CONTEXT — Central server/VPS read-only (system-agent); not the user device]\n"
        "Injected when include_platform_context is enabled and include_host_context=true or text trigger matches.\n"
        "Base system claims **only** on these lines; if a field is missing, say it is not available.\n"
        f"{block}"
    )


def build_post_host_system_message(host_payload: dict[str, Any]) -> dict[str, str]:
    return {"role": "system", "content": format_host_context_for_prompt(host_payload)}


def truncate_session_history(
    history: list[dict[str, str]],
    *,
    max_messages: int,
) -> tuple[list[dict[str, str]], bool]:
    """
    Keep only the last `max_messages` messages of the current session.
    Returns (trimmed_history, truncated_flag).
    """
    if max_messages <= 0 or len(history) <= max_messages:
        return history, False
    trimmed = history[-max_messages:]
    notice = {
        "role": "system",
        "content": (
            "[NOTICE] Part of this session history was omitted (long memory disabled). "
            "To retain more messages or summarize older chat, the client must send "
            "include_long_session_memory=true on the request."
        ),
    }
    return [notice, *trimmed], True
