"""Token budget allocator step — accurate token counting via tiktoken.

Phase: assemble.
Priority: 7 (after merge, before build).

Uses TokenCounter (tiktoken cl100k_base) with chars/4 fallback.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §7
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)


@register_step
class TokenBudgetStep:
    """Calculates token budget using tiktoken for accurate estimation.

    Phase: assemble.
    Priority: 7.
    """

    name = "assemble.token_budget"
    phase = Phase.ASSEMBLE
    priority = 7

    async def should_run(self, state: ContextState) -> bool:
        return True

    async def run(self, state: ContextState) -> ContextState:
        from app.context_engine.token_counter import TokenCounter, get_token_counter
        from app.model_catalog import get_compaction_threshold

        counter = get_token_counter()

        # Dynamic compaction threshold from model catalog (per-model)
        model_id = state.meta.get("model_id", "openai/gpt-4o-mini")
        state.budget.max_total = get_compaction_threshold(model_id)
        budget = state.budget

        # ── L0-L4: system layer messages ────────────────────────
        budget.l0_l4 = counter.count_messages(state.messages)

        # ── L5: RAG sections ────────────────────────────────────
        l5_chars = "".join(s.content for s in state.sections if s.layer == "L5")
        budget.l5_rag = counter.count(l5_chars)

        # ── L7: tool schemas (calculate before L6 for accurate budget) ─
        budget.l7_tools = counter.count_tools(state.tools)

        # ── L6: history (compacted) — gets remaining space ─────
        budget.l6_window = budget.available_for_l6()

        if budget.is_over_budget():
            logger.warning(
                "Token budget exceeded: l0_l4=%d l5=%d l6=%d l7=%d max=%d tiktoken=%s",
                budget.l0_l4, budget.l5_rag, budget.l6_window,
                budget.l7_tools, budget.max_total,
                counter.available,
            )

        state.meta["token_budget"] = {
            "l0_l4": budget.l0_l4,
            "l5_rag": budget.l5_rag,
            "l6_window": budget.l6_window,
            "l7_tools": budget.l7_tools,
            "max_total": budget.max_total,
            "over_budget": budget.is_over_budget(),
            "tiktoken_available": counter.available,
        }

        return state
