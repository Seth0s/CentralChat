"""Resolve execution mode — normalizes mode and connector state.

Phase: resolve (sync, <5ms).
Priority: 40.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §8.3
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class ResolveExecutionMode:
    """Resolves execution mode and sets capability flags.

    Phase: resolve.
    Priority: 40.
    """

    name = "resolve.execution_mode"
    phase = Phase.RESOLVE
    priority = 40

    _VALID_MODES = {"web", "cli"}

    async def should_run(self, state: ContextState) -> bool:
        return True  # Always runs

    async def run(self, state: ContextState) -> ContextState:
        # Normalize mode
        if state.mode not in self._VALID_MODES:
            state.mode = "web"

        # Set capability flags based on mode
        state.meta["execution_mode"] = state.mode
        state.meta["connector_alive"] = state.connector_alive

        return state
