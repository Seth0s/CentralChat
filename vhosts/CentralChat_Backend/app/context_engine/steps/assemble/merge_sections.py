"""Merge sections step — merges all PromptSections into system messages.

Phase: assemble.
Priority: 5 (runs before budget allocation).

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §3.3
"""

from __future__ import annotations

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState


@register_step
class MergeSectionsStep:
    """Merges accumulated PromptSections into system messages.

    Ordered by layer (L0 → L7). Each section becomes a system message
    with appropriate delimiters and trust_level annotations.

    Phase: assemble.
    Priority: 5 (first assemble step).
    """

    name = "assemble.merge_sections"
    phase = Phase.ASSEMBLE
    priority = 5

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.sections)

    async def run(self, state: ContextState) -> ContextState:
        # Sort sections by layer
        layer_order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "L6": 6, "L7": 7}
        sorted_sections = sorted(
            state.sections,
            key=lambda s: layer_order.get(s.layer, 99),
        )

        for section in sorted_sections:
            # Build trust annotation
            trust_annotation = ""
            if section.trust_level == "retrieved":
                trust_annotation = " [retrieved — may contain inaccuracies]"

            state.messages.append({
                "role": "system",
                "content": f"[{section.kind.upper()} {section.layer}]{trust_annotation}\n{section.content}",
            })

        state.meta["sections_merged"] = len(sorted_sections)
        return state
