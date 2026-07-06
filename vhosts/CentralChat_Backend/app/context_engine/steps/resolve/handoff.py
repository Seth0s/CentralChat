"""Resolve handoff/fork — handles session handoff between developers.

Phase: resolve (sync, <5ms).
Priority: 25.

When handoff_from_session_id is present:
- Records audit trail (actor, target session, work_item_id)
- Injects handoff summary as a PromptSection
- For fork: clears history (new context from same WI)
- For observe: marks session as read-only

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.3
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)


@register_step
class ResolveHandoff:
    """Resolves handoff/fork/observe session modes.

    When handoff_from_session_id is set or session_mode is not "continue":
    - fork: clear history, keep WI context
    - observe: mark read-only (no write tools)
    - handoff: add handoff summary, share ACL

    Phase: resolve.
    Priority: 25.
    """

    name = "resolve.handoff"
    phase = Phase.RESOLVE
    priority = 25

    async def should_run(self, state: ContextState) -> bool:
        return (
            bool(state.handoff_from_session_id)
            or state.session_mode != "continue"
        )

    async def run(self, state: ContextState) -> ContextState:
        mode = state.session_mode or "continue"

        # ── Fork ────────────────────────────────────────────────
        if mode == "fork":
            state.meta["session_forked"] = True
            state.meta["fork_from_session"] = state.handoff_from_session_id
            # Clear history for fresh context (keep WI context from ResolveWorkItem)
            state.history = []
            logger.info(
                "Session forked from %s → new session (WI=%s)",
                state.handoff_from_session_id, state.work_item_id,
            )
            return state

        # ── Observe ─────────────────────────────────────────────
        if mode == "observe":
            state.meta["session_observe"] = True
            state.meta["observe_from_session"] = state.handoff_from_session_id
            # Observer: read-only — enforce via empty role allowlist
            state.role_tool_allowlist = frozenset({
                "memory", "session_search", "clarify",
                "read_file", "search_files",
            })
            state.role = "observer"
            logger.info(
                "Session observe mode from %s (WI=%s)",
                state.handoff_from_session_id, state.work_item_id,
            )
            return state

        # ── Handoff ─────────────────────────────────────────────
        if state.handoff_from_session_id:
            state.meta["session_handoff"] = True
            state.meta["handoff_from_session"] = state.handoff_from_session_id
            state.meta["handoff_work_item"] = state.work_item_id

            # Inject handoff summary section
            section = PromptSection(
                layer="L2",
                kind="handoff",
                content=(
                    f"[HANDOFF L2 — from session {state.handoff_from_session_id}]\n"
                    f"Work Item: {state.work_item_id or 'N/A'}\n"
                    f"Role: {state.role}\n"
                    f"Previous context has been summarized. Continue from here."
                ),
                provenance=f"session_handoff:{state.handoff_from_session_id}",
                trust_level="operational",
                char_budget=300,
            )
            state.sections.append(section)

            # Load summary from previous session if available
            await self._inject_handoff_summary(state)

            logger.info(
                "Handoff from session %s to %s (WI=%s user=%s)",
                state.handoff_from_session_id, state.session_id,
                state.work_item_id, state.user_id,
            )

        return state

    async def _inject_handoff_summary(self, state: ContextState) -> None:
        """Load and inject summary from the previous session."""
        import asyncio

        try:
            summary = await asyncio.to_thread(
                _load_session_summary,
                state.handoff_from_session_id,
                state.tenant_id,
            )
            if summary:
                section = PromptSection(
                    layer="L2",
                    kind="handoff_summary",
                    content=f"[HANDOFF SUMMARY]\n{summary[:1000]}",
                    provenance=f"session_summaries:{state.handoff_from_session_id}",
                    trust_level="retrieved",
                    char_budget=min(len(summary), 1000),
                )
                state.sections.append(section)
        except Exception:
            logger.debug("Handoff summary load failed", exc_info=True)


def _load_session_summary(session_id: str | None, tenant_id: str) -> str | None:
    """Load the latest summary from a session."""
    if not session_id:
        return None
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT summary_text FROM session_summaries "
                "WHERE tenant_id=%s AND session_id=%s "
                "ORDER BY version DESC LIMIT 1",
                (tenant_id, session_id),
            )
            row = cur.fetchone()
            if row:
                return str(row[0])
    except Exception:
        pass
    return None
