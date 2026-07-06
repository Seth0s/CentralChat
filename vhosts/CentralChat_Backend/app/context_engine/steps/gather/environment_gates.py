"""Environment gates — WI label → skill/tool relevance filtering.

When a work_item has labels, filter the tool catalog to only include
tools relevant to those labels (e.g., "backend" label → exclude frontend-only tools).

Maps WI labels to allowed tool categories for scoped context.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.10 (H-6)
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)

# Label → relevant tool categories
# Labels without a mapping get all non-delegated tools (default behavior)
_LABEL_TOOL_SCOPE: dict[str, set[str]] = {
    "backend": {"terminal", "read_file", "write_file", "patch", "search_files",
                 "execute_code", "delegate_task"},
    "frontend": {"read_file", "search_files", "write_file", "patch",
                  "web_search", "vision_analyze"},
    "docs": {"read_file", "search_files", "write_file", "web_search"},
    "devops": {"terminal", "read_file", "search_files", "delegate_task",
                "execute_code", "cronjob"},
    "testing": {"terminal", "read_file", "search_files", "execute_code"},
    "security": {"read_file", "search_files", "terminal", "session_search"},
    "data": {"terminal", "read_file", "search_files", "execute_code", "web_search"},
}

# TIER_0 tools always available regardless of label scope
_TIER_0 = {"memory", "session_search", "clarify", "ask_project"}


@register_step
class EnvironmentGateStep:
    """Filters tool catalog based on WI labels (environment gates).

    When a work_item has labels matching predefined scopes,
    restricts the tool catalog to relevant categories.

    Phase: gather (after file_lease, before tool_selection).
    Priority: 18.
    """

    name = "gather.environment_gates"
    phase = Phase.GATHER
    priority = 13  # After file_lease (12), before retrieval (15)

    async def should_run(self, state: ContextState) -> bool:
        labels = state.meta.get("work_item_labels") or []
        return bool(labels)

    async def run(self, state: ContextState) -> ContextState:
        labels = state.meta.get("work_item_labels") or []
        if not labels:
            return state

        # Build allowed tool set from label mappings
        allowed: set[str] = set(_TIER_0)
        for label in labels:
            label_lower = label.lower()
            scope = _LABEL_TOOL_SCOPE.get(label_lower)
            if scope:
                allowed.update(scope)

        # If no label matched any scope, allow all (no restriction)
        matched = any(label.lower() in _LABEL_TOOL_SCOPE for label in labels)
        if not matched:
            state.meta["environment_gates_applied"] = False
            return state

        # Store allowed set for ToolSelectionStep to use
        state.meta["environment_gates_applied"] = True
        state.meta["environment_allowed_tools"] = sorted(allowed)
        state.meta["environment_matched_labels"] = [
            l for l in labels if l.lower() in _LABEL_TOOL_SCOPE
        ]

        logger.debug(
            "Environment gates: labels=%s allowed_tools=%d",
            labels, len(allowed),
        )

        return state
