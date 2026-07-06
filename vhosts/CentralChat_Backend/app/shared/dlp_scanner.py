"""H2 — DLP pre-prompt scanner (regex patterns for secrets/PII)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import CENTRAL_DLP_ENABLED

_DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("aws_access_key", r"(?i)AKIA[0-9A-Z]{16}"),
    ("private_key_block", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ("github_token", r"(?i)ghp_[A-Za-z0-9]{20,}"),
    ("gitlab_token", r"(?i)glpat-[A-Za-z0-9\-_]{20,}"),
    ("generic_api_key", r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b"),
    ("cpf_br", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
)


@dataclass
class DlpScanResult:
    allowed: bool
    hits: list[str]
    message_pt: str | None = None


def scan_prompt_text(
    text: str,
    *,
    extra_patterns: list[str] | None = None,
    tenant_id: str | None = None,
) -> DlpScanResult:
    """Return blocked result when sensitive patterns match."""
    from app.config import CENTRAL_DLP_TENANT_ALLOWLIST
    from app.shared.pg_tenant import resolve_pg_tenant_id

    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if tid in CENTRAL_DLP_TENANT_ALLOWLIST:
        return DlpScanResult(allowed=True, hits=[])
    if not CENTRAL_DLP_ENABLED:
        return DlpScanResult(allowed=True, hits=[])
    body = (text or "").strip()
    if not body:
        return DlpScanResult(allowed=True, hits=[])
    hits: list[str] = []
    for name, pat in _DEFAULT_PATTERNS:
        if re.search(pat, body):
            hits.append(name)
    for raw in extra_patterns or []:
        try:
            if re.search(raw, body):
                hits.append(f"custom:{raw[:40]}")
        except re.error:
            continue
    if hits:
        return DlpScanResult(
            allowed=False,
            hits=hits,
            message_pt="Conteúdo bloqueado pela política DLP (dados sensíveis detectados).",
        )
    return DlpScanResult(allowed=True, hits=[])
