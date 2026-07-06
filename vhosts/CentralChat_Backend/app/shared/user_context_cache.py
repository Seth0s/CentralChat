"""T12 — User Context Cache (VPS side).

Receives user context blobs from the connector, caches them by tenant_id,
computes diffs to avoid re-processing unchanged data, and triggers async
embedding indexing for skills.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.shared.pg_tenant import resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# ═══ CACHE ═══

_cache: dict[str, _UserContextEntry] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 3600  # 1 hour


@dataclass
class _UserContextEntry:
    """Cached user context with hash-based diff."""

    identity_hash: str = ""
    agents_hash: str = ""
    skills_hash: str = ""
    tools_hash: str = ""
    identity: dict[str, Any] = field(default_factory=dict)
    agents: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0


def _compute_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def sync_user_context(
    tenant_id: str,
    *,
    identity: dict[str, Any] | None = None,
    agents: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Receive and cache user context from connector. Returns diff summary:
    which sections changed and whether re-indexing is needed.
    """
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    now = time.monotonic()
    diff: dict[str, bool] = {}

    with _cache_lock:
        entry = _cache.get(tid)
        if entry is None:
            entry = _UserContextEntry()
            _cache[tid] = entry

        # Identity
        if identity is not None:
            h = _compute_hash(identity)
            if h != entry.identity_hash:
                entry.identity = identity
                entry.identity_hash = h
                diff["identity"] = True

        # Agents
        if agents is not None:
            h = _compute_hash(agents)
            if h != entry.agents_hash:
                entry.agents = agents
                entry.agents_hash = h
                diff["agents"] = True

        # Skills
        if skills is not None:
            h = _compute_hash(skills)
            if h != entry.skills_hash:
                entry.skills = skills
                entry.skills_hash = h
                diff["skills"] = True

        # Tools
        if tools is not None:
            h = _compute_hash(tools)
            if h != entry.tools_hash:
                entry.tools = tools
                entry.tools_hash = h
                diff["tools"] = True

        entry.updated_at = now

    # Trigger async skill embedding if skills changed
    if diff.get("skills") and skills:
        try:
            _index_skills_async(tid, skills)
        except Exception:
            pass

    return {
        "tenant_id": tid,
        "changes": diff,
        "cached_at": now,
        "identity_name": entry.identity.get("name", ""),
        "agent_count": len(entry.agents),
        "skill_count": len(entry.skills),
        "tool_count": len(entry.tools),
    }


def get_cached_identity(tenant_id: str) -> dict[str, Any]:
    """Get cached identity for a user."""
    with _cache_lock:
        entry = _cache.get(tenant_id)
        return dict(entry.identity) if entry else {}


def get_cached_agents(tenant_id: str) -> list[dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(tenant_id)
        return list(entry.agents) if entry else []


def get_cached_skills(tenant_id: str) -> list[dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(tenant_id)
        return list(entry.skills) if entry else []


def _index_skills_async(tenant_id: str, skills: list[dict[str, Any]]) -> None:
    """Queue skill content for embedding (fire-and-forget)."""
    from app.shared.embedding_cache import enqueue_embedding_job

    for skill in skills:
        name = skill.get("name", "unknown")
        content = skill.get("content", "")
        if content:
            enqueue_embedding_job(
                text=content,
                tenant_id=tenant_id,
                kind="skill",
                source_key=name,
            )


def context_cache_stats() -> dict[str, Any]:
    """Debug: cache state."""
    with _cache_lock:
        return {
            "entries": len(_cache),
            "tenants": list(_cache.keys()),
        }
