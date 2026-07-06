"""Build messages step — assembles the final message array from all layers.

Extracted from context_pipeline.py:assemble() final build section.
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class BuildMessagesStep:
    """Merges system layers, tools catalog, compacted history, and user text.

    Phase: assemble (runs after all gather steps).
    Priority: 10.
    """

    name = "assemble.build_messages"
    phase = Phase.ASSEMBLE
    priority = 10

    async def should_run(self, state: ContextState) -> bool:
        return True

    async def run(self, state: ContextState) -> ContextState:
        injected: list[dict[str, str]] = []

        # System layers (L1-L4 + ENV from SystemLayersStep)
        injected.extend(state.messages)

        # Tools catalog
        if state.tool_catalog:
            injected.append({
                "role": "system",
                "content": f"[TOOLS] {', '.join(state.tool_catalog)}",
            })

        # Compacted history (from CompactionPrepStep)
        injected.extend(state.history)

        # User text (always last)
        injected.append({"role": "user", "content": state.user_text})

        state.messages = injected

        # Ensure L5 is tracked if compaction happened
        if state.session_truncated and "L5" not in state.layers_applied:
            state.layers_applied.append("L5")

        return state
