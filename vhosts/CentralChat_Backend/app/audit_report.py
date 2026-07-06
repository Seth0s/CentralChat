"""H3 — Structured audit reports (JSON + minimal PDF)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.audit_service import list_audit_events
from app.shared.pg_tenant import resolve_pg_tenant_id


def _norm_path_prefix(prefix: str | None) -> str:
    return (prefix or "").strip().replace("\\", "/").lower()


def _event_matches_path(ev: dict[str, Any], path_prefix: str) -> bool:
    if not path_prefix:
        return True
    resource = str(ev.get("resource") or "").lower()
    meta = ev.get("metadata") if isinstance(ev.get("metadata"), dict) else {}
    for key in ("path", "cwd", "file", "tool", "violation"):
        v = meta.get(key)
        if isinstance(v, str) and path_prefix in v.lower():
            return True
    return path_prefix in resource


def build_audit_report(
    *,
    since: str | None = None,
    path_prefix: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    limit: int = 5000,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    rows = list_audit_events(since=since, user_id=user_id, action=action, limit=limit, tenant_id=tid)
    prefix = _norm_path_prefix(path_prefix)
    if prefix:
        rows = [r for r in rows if _event_matches_path(r, prefix)]
    by_action: Counter[str] = Counter()
    by_user: Counter[str] = Counter()
    for row in rows:
        by_action[str(row.get("action") or "unknown")] += 1
        uid = str(row.get("user_id") or "anonymous")
        by_user[uid] += 1
    generated = datetime.now(timezone.utc).isoformat()
    return {
        "tenant_id": tid,
        "generated_at": generated,
        "filters": {
            "since": since,
            "path_prefix": path_prefix,
            "user_id": user_id,
            "action": action,
            "limit": limit,
        },
        "summary": {
            "total_events": len(rows),
            "by_action": dict(by_action.most_common(50)),
            "top_users": [
                {"user_id": uid, "count": cnt}
                for uid, cnt in by_user.most_common(20)
            ],
        },
        "items": rows,
    }


def export_audit_report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def _pdf_lines(report: dict[str, Any]) -> list[str]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    filters = report.get("filters") if isinstance(report.get("filters"), dict) else {}
    lines = [
        "CentralChat Audit Report",
        f"Tenant: {report.get('tenant_id', 'default')}",
        f"Generated: {report.get('generated_at', '')}",
        f"Since: {filters.get('since') or 'all'}",
        f"Path prefix: {filters.get('path_prefix') or 'any'}",
        f"Total events: {summary.get('total_events', 0)}",
        "",
        "By action:",
    ]
    by_action = summary.get("by_action") if isinstance(summary.get("by_action"), dict) else {}
    for act, cnt in list(by_action.items())[:15]:
        lines.append(f"  {act}: {cnt}")
    lines.append("")
    lines.append("Recent events (max 40):")
    items = report.get("items") if isinstance(report.get("items"), list) else []
    for ev in items[:40]:
        if not isinstance(ev, dict):
            continue
        lines.append(
            f"  {str(ev.get('created_at', ''))[:19]}  {ev.get('action', '')}  {ev.get('resource', '') or '-'}"
        )
    return lines


def export_audit_report_pdf(report: dict[str, Any]) -> bytes:
    """Minimal single-page PDF (stdlib only, no external deps)."""
    lines = _pdf_lines(report)
    y = 780
    content_parts: list[str] = ["BT /F1 9 Tf"]
    for line in lines:
        safe = _pdf_escape(line[:120])
        content_parts.append(f"50 {y} Td ({safe}) Tj")
        y -= 14
        if y < 60:
            break
    content_parts.append("ET")
    stream = "\n".join(content_parts)
    stream_bytes = stream.encode("latin-1", errors="replace")
    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream_bytes)} >>stream\n".encode()
        + stream_bytes
        + b"\nendstream endobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    header = b"%PDF-1.4\n"
    body = b""
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        body += obj
        pos += len(obj)
    xref_pos = pos
    xref = f"xref\n0 {len(offsets)}\n0000000000 65535 f \n"
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n"
    trailer = (
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    return header + body + xref.encode() + trailer.encode()
