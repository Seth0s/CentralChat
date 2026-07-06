"""Tool selection step — keyword-driven selection with SchemaTracker.

Integrates SchemaTracker to avoid re-injecting schemas that are
already present in the current context window. After compaction,
only missing tools are re-injected.

Phase: gather.
Priority: 20.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §8.1
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class ToolSelectionStep:
    """Selects tool schemas with schema tracking across turns.

    Phase: gather.
    Priority: 20.
    """

    name = "gather.tool_selection"
    phase = Phase.GATHER
    priority = 20

    async def should_run(self, state: ContextState) -> bool:
        return True

    async def run(self, state: ContextState) -> ContextState:
        from app.context_engine.schema_tracker import get_schema_tracker
        from app.context_pipeline import ToolInjector

        injector = ToolInjector()
        tools, catalog_names = injector.select_and_inject(
            state.user_text,
            history=state.history,
            current_messages=list(state.messages),
            connector_alive=state.connector_alive,
        )

        # ── Schema tracking ──────────────────────────────────────
        tracker = get_schema_tracker(state.session_id or None)

        # Check which tools need re-injection after compaction
        if state.session_truncated:
            tracker.handle_compaction(list(state.messages))

        # Filter to only new/changed schemas
        tools_registry = {t["function"]["name"]: t for t in tools}
        missing_names = tracker.get_missing(tools_registry, list(state.messages))

        # Always inject TIER_0 tools
        tier_0_present = InjectorConstants.TIER_0 & set(tools_registry.keys())

        final_tools = []
        for t in tools:
            name = t["function"]["name"]
            # RBAC: filter by role tool allowlist if set
            if (state.role_tool_allowlist and
                    name not in state.role_tool_allowlist and
                    name not in tier_0_present):
                continue
            if name in missing_names or name in tier_0_present:
                final_tools.append(t)
                tracker.mark_injected(name, t)

        state.tools = final_tools
        state.tool_catalog = list(catalog_names)
        state.meta["tools_injected"] = len(final_tools)
        state.meta["tools_tracked"] = len(tracker.active)
        state.meta["tools_new_or_changed"] = missing_names
        if state.role_tool_allowlist:
            state.meta["tools_role_scoped"] = True
            state.meta["tools_role"] = state.role

        return state


class InjectorConstants:
    """Constants shared with ToolInjector — sourced from tool_catalog."""
    from app.tool_catalog import TIER_0 as _T0  # noqa: E402

    TIER_0: set[str] = _T0
