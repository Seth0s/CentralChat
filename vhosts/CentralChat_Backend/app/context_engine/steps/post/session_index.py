"""Session indexing post step — indexes completed turn into pgvector.

Phase: post (background).
Priority: 10.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §3.3 (post phase)
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)


@register_step
class SessionIndexStep:
    """Indexes the completed turn into session RAG (pgvector).

    Calls ingest_session_turn_facts() from app.rag to extract
    facts from user_text + assistant response and index them
    for future session RAG retrieval.

    Phase: post (background, after LLM response).
    Priority: 10.
    """

    name = "post.session_index"
    phase = Phase.POST
    priority = 10

    async def should_run(self, state: ContextState) -> bool:
        return (
            bool(state.session_id)
            and bool(state.user_text.strip())
            and not state.focus_mode
        )

    async def run(self, state: ContextState) -> ContextState:
        try:
            from app.config import CENTRAL_SESSION_RAG_ENABLED

            if not CENTRAL_SESSION_RAG_ENABLED:
                state.meta["session_indexed"] = False
                return state

            # Extract the assistant response from messages
            assistant_text = self._extract_assistant_response(state)

            from app.rag import ingest_session_turn_facts

            # Onda 5: DLP scan on facts before indexing
            facts_raw = [state.user_text, assistant_text]
            from app.onda5_hardening import dlp_scan_facts

            clean_facts = dlp_scan_facts(facts_raw, state.tenant_id)
            if not clean_facts:
                state.meta["session_indexed"] = False
                state.meta["session_dlp_blocked"] = True
                return state

            count = await self._run_ingest(
                ingest_session_turn_facts,
                chat_session_id=state.session_id or "",
                user_text=clean_facts[0] if clean_facts else state.user_text,
                assistant_text=clean_facts[1] if len(clean_facts) > 1 else assistant_text,
                tenant_id=state.tenant_id,
            )

            state.meta["session_indexed"] = True
            state.meta["session_facts_count"] = count or 0
            logger.debug(
                "Session indexed session_id=%s facts=%d",
                state.session_id, count or 0,
            )

        except Exception:
            logger.debug(
                "Session indexing failed for session_id=%s",
                state.session_id, exc_info=True,
            )
            state.meta["session_indexed"] = False

        return state

    @staticmethod
    def _extract_assistant_response(state: ContextState) -> str:
        """Extract the assistant's last response from messages."""
        for msg in reversed(state.messages):
            if msg.get("role") == "assistant":
                return str(msg.get("content", ""))
        return ""

    @staticmethod
    async def _run_ingest(ingest_fn, **kwargs) -> int | None:
        """Run ingest in a thread to avoid blocking the event loop."""
        import asyncio

        return await asyncio.to_thread(ingest_fn, **kwargs)
