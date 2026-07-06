"""File lease step — prevents clobber by tracking active file locks per WI.

Phase: gather (before tool selection, after system layers).
Priority: 12.

When a work_item is in_progress, tracks which path_prefix files are
actively being edited. If another session tries to modify a leased file,
injects a [LEASE_CONFLICT] warning into the context.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.6
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)

# In-memory lease store (per tenant/WI)
# Key: (tenant_id, path_prefix) → {work_item_id, session_id, claimed_at, user_id}
_lease_store: dict[tuple[str, str], dict[str, Any]] = {}

# Lease timeout: auto-release after 30 minutes of inactivity
_LEASE_TIMEOUT_S = 30 * 60


@register_step
class FileLeaseStep:
    """Tracks and enforces file leases per work item.

    Phase: gather.
    Priority: 12.
    """

    name = "gather.file_lease"
    phase = Phase.GATHER
    priority = 12

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.work_item_id and state.workspace_path)

    async def run(self, state: ContextState) -> ContextState:
        wi = state.work_item_id
        ws = state.workspace_path or ""
        tid = state.tenant_id

        # Claim the lease for this WI + path
        key = (tid, ws)
        existing = _lease_store.get(key)

        if existing:
            # Check if lease is stale
            age = time.time() - existing.get("claimed_at", 0)
            if age > _LEASE_TIMEOUT_S:
                logger.info("Stale lease released: %s (age=%ds)", key, age)
                _lease_store.pop(key, None)
            elif existing.get("work_item_id") != wi:
                # Conflict: different WI has the lease
                self._inject_conflict(state, existing)
                return state
            # Same WI — renew lease
            existing["claimed_at"] = time.time()
            existing["session_id"] = state.session_id
        else:
            # Claim new lease
            _lease_store[key] = {
                "work_item_id": wi,
                "session_id": state.session_id,
                "user_id": state.user_id,
                "claimed_at": time.time(),
            }

        state.meta["file_lease_active"] = True
        state.meta["file_lease_wi"] = wi
        state.meta["file_lease_path"] = ws

        # Inject L2 branch suggestion
        if not self._has_branch_injected(state):
            branch = self._suggest_branch(wi, ws)
            section = PromptSection(
                layer="L2",
                kind="file_lease",
                content=(
                    f"[FILE_LEASE L2 — Workspace locked for this WI]\n"
                    f"Work Item: {wi}\n"
                    f"Path: {ws}\n"
                    f"Suggested branch: {branch}\n"
                    f"User: {state.user_id}"
                ),
                provenance=f"file_leases:{tid}:{ws}",
                trust_level="operational",
                char_budget=300,
            )
            state.sections.append(section)

        return state

    def _inject_conflict(self, state: ContextState, existing: dict) -> None:
        """Inject a lease conflict warning."""
        section = PromptSection(
            layer="L2",
            kind="lease_conflict",
            content=(
                f"[LEASE_CONFLICT L2]\n"
                f"Workspace {state.workspace_path} is leased by WI {existing.get('work_item_id')} "
                f"(user {existing.get('user_id')}, session {existing.get('session_id')}).\n"
                f"Your WI {state.work_item_id} cannot modify these files until the lease is released."
            ),
            provenance="file_leases:conflict",
            trust_level="operational",
            char_budget=400,
        )
        state.sections.append(section)
        state.meta["file_lease_conflict"] = True
        state.meta["file_lease_conflict_wi"] = existing.get("work_item_id")

    @staticmethod
    def _suggest_branch(wi: str | None, ws: str) -> str:
        """Suggest a git branch name for the WI."""
        if not wi:
            return "work/unnamed"
        slug = wi.lower().replace(" ", "-").replace("_", "-")
        return f"wi/{slug}"

    @staticmethod
    def _has_branch_injected(state: ContextState) -> bool:
        """Check if a branch suggestion was already injected."""
        return any(s.kind == "file_lease" for s in state.sections)


def release_lease(tenant_id: str, workspace_path: str) -> bool:
    """Release a file lease (called when WI is closed)."""
    key = (tenant_id, workspace_path)
    if key in _lease_store:
        _lease_store.pop(key)
        return True
    return False


def get_active_lease(tenant_id: str, workspace_path: str) -> dict | None:
    """Get the active lease for a workspace path."""
    key = (tenant_id, workspace_path)
    return _lease_store.get(key)
