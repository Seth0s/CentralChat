"""Resolve work item — injects WI as L2 anchor when work_item_id is present.

Phase: resolve (sync, <5ms).
Priority: 20.

Looks up work item metadata from PG (work_items table) and injects
a deterministic [WORK_ITEM L2] block with title, description, status,
priority, assignee, workspace_path, repo, labels, and pending approvals.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.1
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)


@register_step
class ResolveWorkItem:
    """Resolves work item context and injects L2 block.

    When work_item_id is present in the request:
    1. Validates tenant ownership
    2. Looks up WI metadata from work_items table
    3. Injects [WORK_ITEM L2] block as PromptSection

    Phase: resolve.
    Priority: 20.
    """

    name = "resolve.work_item"
    phase = Phase.RESOLVE
    priority = 20

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.work_item_id)

    async def run(self, state: ContextState) -> ContextState:
        import asyncio

        try:
            wi = await asyncio.to_thread(
                _lookup_work_item,
                state.work_item_id,
                state.tenant_id,
            )
        except Exception:
            logger.debug("WI lookup failed for %s", state.work_item_id, exc_info=True)
            state.meta["work_item_resolved"] = state.work_item_id
            state.meta["work_item_state"] = "lookup_failed"
            return state

        if not wi:
            logger.warning("WI not found: %s (tenant=%s)", state.work_item_id, state.tenant_id)
            state.meta["work_item_resolved"] = state.work_item_id
            state.meta["work_item_state"] = "not_found"
            return state

        # Build L2 block
        block = self._build_wi_block(wi)
        section = PromptSection(
            layer="L2",
            kind="work_item",
            content=block,
            provenance=f"work_items:{state.work_item_id}",
            trust_level="curated",
            char_budget=len(block),
        )
        state.sections.append(section)
        state.layers_applied.append("L2")

        # Store WI metadata for use by other steps
        state.meta["work_item_resolved"] = state.work_item_id
        state.meta["work_item_state"] = wi.get("status", "unknown")
        state.meta["work_item_assignee"] = wi.get("assignee_id")
        state.meta["work_item_repo"] = wi.get("repo")
        state.meta["work_item_workspace"] = wi.get("workspace_path")
        state.meta["work_item_labels"] = wi.get("labels", [])
        state.meta["work_item_approval_ids"] = wi.get("approval_ids", [])
        state.meta["work_item_agent_name"] = wi.get("agent_name")

        # ── Bloco A: Inject agent_name + skills as L3 context ──
        agent_name = wi.get("agent_name")
        skills = wi.get("skills", [])
        if agent_name or skills:
            l3_block = _build_l3_block(agent_name, skills)
            state.sections.append(PromptSection(
                layer="L3",
                kind="work_item_agent",
                content=l3_block,
                provenance=f"work_items:{state.work_item_id}",
                trust_level="curated",
                char_budget=len(l3_block),
            ))
            state.layers_applied.append("L3")
            # Set agent_name from WI if not already set
            if agent_name and not state.agent_name:
                state.agent_name = agent_name

        # Use WI workspace_path as fallback if none provided
        if not state.workspace_path and wi.get("workspace_path"):
            state.workspace_path = wi["workspace_path"]

        return state

    @staticmethod
    def _build_wi_block(wi: dict) -> str:
        """Build a compact [WORK_ITEM L2] block from WI metadata."""
        lines = [f"[WORK_ITEM L2 — {wi.get('id', '?')}]"]

        title = wi.get("title", "sem título")
        lines.append(f"Title: {title}")

        status = wi.get("status", "open")
        priority = wi.get("priority", "normal")
        lines.append(f"Status: {status} | Priority: {priority}")

        if wi.get("assignee_id"):
            lines.append(f"Assignee: {wi['assignee_id']}")

        if wi.get("repo"):
            lines.append(f"Repo: {wi['repo']}")

        if wi.get("workspace_path"):
            lines.append(f"Workspace: {wi['workspace_path']}")

        if wi.get("description"):
            desc = wi["description"][:500]
            lines.append(f"Description: {desc}")

        labels = wi.get("labels") or []
        if labels:
            lines.append(f"Labels: {', '.join(labels)}")

        approval_ids = wi.get("approval_ids") or []
        if approval_ids:
            lines.append(f"Pending approvals: {len(approval_ids)}")

        source = wi.get("source", "manual")
        if source != "manual":
            lines.append(f"Source: {source}")

        return "\n".join(lines)


def _build_l3_block(agent_name: str | None, skills: list[str]) -> str:
    """Build L3 context block for WI agent + skills."""
    lines = ["[WORK_ITEM_AGENT]"]
    if agent_name:
        lines.append(f"Agent: {agent_name}")
    if skills:
        lines.append(f"Skills: {', '.join(skills)}")
    return "\n".join(lines)


def _lookup_work_item(item_id: str, tenant_id: str) -> dict | None:
    """Look up work item from PG (synchronous, called via asyncio.to_thread)."""
    try:
        from app.work_queue import get_work_item

        return get_work_item(item_id, tenant_id=tenant_id)
    except Exception:
        return None
