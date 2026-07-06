"""Resolve active document — validates and normalizes active_document_id.

Phase: resolve (sync, <5ms).
Priority: 30.
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class ResolveActiveDocument:
    """Resolves and validates the active document reference.

    Phase: resolve.
    Priority: 30.
    """

    name = "resolve.active_document"
    phase = Phase.RESOLVE
    priority = 30

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.active_document_id)

    async def run(self, state: ContextState) -> ContextState:
        # Stub: validate active_document_id format
        # Full implementation when document upload/indexing is complete
        if not isinstance(state.active_document_id, str):
            state.active_document_id = None

        state.meta["active_document_validated"] = bool(state.active_document_id)
        return state
