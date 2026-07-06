"""Audit JSONL do orquestrador (decision layer)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from app.config import ORCHESTRATOR_AUDIT_LOG_PATH

log = logging.getLogger(__name__)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            log.warning("orchestrator audit: nao criou diretorio %s: %s", parent, exc)


def write_event(event: dict) -> None:
    enriched = dict(event)
    enriched.setdefault("ts", datetime.now(timezone.utc).isoformat())
    enriched.setdefault("source", "orchestrator")
    _ensure_parent(ORCHESTRATOR_AUDIT_LOG_PATH)
    line = json.dumps(enriched, ensure_ascii=False)
    try:
        with open(ORCHESTRATOR_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        # SELinux sem :z no volume, permissoes do host, etc. — nao derrubar o pedido HTTP
        log.warning(
            "orchestrator audit: falha ao escrever %s (%s). Ver permissoes do host ou :z no compose.",
            ORCHESTRATOR_AUDIT_LOG_PATH,
            exc,
        )
        return

    try:
        from app.audit_service import mirror_orchestrator_event

        mirror_orchestrator_event(enriched)
    except Exception as exc:  # noqa: BLE001
        log.debug("audit mirror hook: %s", exc, exc_info=True)
    try:
        from app.playbook import maybe_record_from_audit_event

        maybe_record_from_audit_event(enriched)
    except Exception as exc:  # noqa: BLE001
        log.debug("playbook promotion candidates hook: %s", exc, exc_info=True)
