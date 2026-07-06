"""Onda 5 security hardening utilities.

- DLP on session ingest: scan facts before indexing into pgvector
- ContextPolicy per tenant: PG-backed policy overrides
- Stale diff detection: SHA tracking for pre-approval validation
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DLP on session ingest
# ═══════════════════════════════════════════════════════════════

def dlp_scan_facts(facts: list[str], tenant_id: str) -> list[str]:
    """Filter out facts that contain secrets/PII before indexing.

    Returns only clean facts. Blocked facts are logged (not returned).
    Called by SessionIndexStep before ingest_session_turn_facts().
    """
    try:
        from app.shared.dlp_scanner import scan_prompt_text
    except ImportError:
        return facts

    clean: list[str] = []
    for fact in facts:
        result = scan_prompt_text(fact, tenant_id=tenant_id)
        if result.allowed:
            clean.append(fact)
        else:
            logger.warning(
                "DLP blocked session fact: hits=%s fact_len=%d",
                result.hits, len(fact),
            )

    if len(clean) < len(facts):
        logger.info(
            "DLP filtered %d/%d session facts for tenant=%s",
            len(facts) - len(clean), len(facts), tenant_id,
        )

    return clean


# ═══════════════════════════════════════════════════════════════
# ContextPolicy per tenant (PG-backed)
# ═══════════════════════════════════════════════════════════════

def load_tenant_policy_overrides(tenant_id: str) -> dict[str, Any] | None:
    """Load tenant-specific policy overrides from PG.

    Returns None if no overrides exist (use defaults).
    Uses short timeout to avoid blocking when PG is unavailable.

    Table: tenant_policies (idempotent — create if not exists).
    """
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            return None

        # Use a short-lived connection with explicit connect_timeout
        import os
        os.environ.setdefault("PGOPTIONS", "-c statement_timeout=1000")

        with connect_pg() as conn, conn.cursor() as cur:
            # Ensure table exists (idempotent)
            cur.execute(
                """CREATE TABLE IF NOT EXISTS tenant_policies (
                    tenant_id TEXT PRIMARY KEY,
                    max_context_tokens INT,
                    rag_char_budget INT,
                    verbatim_tail_messages INT,
                    max_tool_schemas INT,
                    dlp_enabled BOOLEAN,
                    focus_mode BOOLEAN,
                    tool_selection TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );"""
            )

            cur.execute(
                "SELECT max_context_tokens, rag_char_budget, verbatim_tail_messages, "
                "max_tool_schemas, dlp_enabled, focus_mode, tool_selection "
                "FROM tenant_policies WHERE tenant_id = %s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return {
                "max_context_tokens": row[0],
                "rag_char_budget": row[1],
                "verbatim_tail_messages": row[2],
                "max_tool_schemas": row[3],
                "dlp_enabled": row[4],
                "focus_mode": row[5],
                "tool_selection": row[6],
            }
    except Exception:
        logger.debug("Tenant policy load failed for %s", tenant_id, exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════
# Stale diff detection
# ═══════════════════════════════════════════════════════════════

# In-memory SHA tracker: (session_id, file_path) → SHA at read time
_file_sha_store: dict[tuple[str, str], str] = {}


def record_file_read(session_id: str, file_path: str, sha: str) -> None:
    """Record the SHA of a file at the time it was read by the agent."""
    _file_sha_store[(session_id, file_path)] = sha


def check_stale_diff(session_id: str, file_path: str, current_sha: str) -> bool:
    """Check if a file has been modified since the agent read it.

    Returns True if the file is stale (SHA changed since read).
    """
    key = (session_id, file_path)
    recorded_sha = _file_sha_store.get(key)
    if recorded_sha is None:
        return False  # No read recorded — can't detect staleness
    return recorded_sha != current_sha


def clear_file_sha(session_id: str, file_path: str | None = None) -> None:
    """Clear SHA records for a session (or specific file)."""
    if file_path:
        _file_sha_store.pop((session_id, file_path), None)
    else:
        to_remove = [k for k in _file_sha_store if k[0] == session_id]
        for k in to_remove:
            _file_sha_store.pop(k, None)
