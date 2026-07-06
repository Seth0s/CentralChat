"""Audit emit — records injection metadata for audit trail.

Phase: post (background).
Priority: 30.
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class AuditEmitStep:
    """Emits audit event with injection metadata.

    Phase: post.
    Priority: 30.
    """

    name = "post.audit_emit"
    phase = Phase.POST
    priority = 30

    async def should_run(self, state: ContextState) -> bool:
        return True  # Always emit audit for traceability

    async def run(self, state: ContextState) -> ContextState:
        # Stub: audit emit to be wired when audit pipeline exists
        state.meta["audit_emitted"] = True
        return state
