"""Resolve session history — validates and normalizes session identity.

Phase: resolve (sync, <5ms).
Priority: 10.
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class ResolveSessionHistory:
    """Resolves session identity and normalizes history.

    Phase: resolve (first step).
    Priority: 10.
    """

    name = "resolve.session_history"
    phase = Phase.RESOLVE
    priority = 10

    async def should_run(self, state: ContextState) -> bool:
        return True  # Always runs — session identity is fundamental

    async def run(self, state: ContextState) -> ContextState:
        # Validate session_id format if present
        if state.session_id and not isinstance(state.session_id, str):
            state.session_id = None

        # Cap history to prevent unbounded memory
        # (compaction happens later in gather phase)
        if len(state.history) > 500:
            state.history = state.history[-500:]

        return state
