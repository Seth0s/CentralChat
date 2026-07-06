"""Async compaction checkpoint — saves session summaries to PG.

Phase: post (background).
Priority: 20.
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class AsyncCheckpointStep:
    """Saves session compaction checkpoint asynchronously.

    Phase: post.
    Priority: 20.
    """

    name = "post.async_checkpoint"
    phase = Phase.POST
    priority = 20

    async def should_run(self, state: ContextState) -> bool:
        return state.session_truncated and bool(state.session_id)

    async def run(self, state: ContextState) -> ContextState:
        # Stub: checkpoint to PG will be wired when compaction is complete
        state.meta["checkpoint_saved"] = False
        return state
