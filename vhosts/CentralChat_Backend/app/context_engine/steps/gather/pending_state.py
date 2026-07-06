"""Pending state step — injects approvals, WI blockers, team requests.

Phase: gather.
Priority: 25.

Collects:
- Approvals awaiting review for this user/session
- WI blocked by policy
- Open team_requests (lead_decision, policy_exception)

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.2
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)


@register_step
class PendingStateStep:
    """Injects pending state block before LLM prompt.

    Phase: gather.
    Priority: 25.
    """

    name = "gather.pending_state"
    phase = Phase.GATHER
    priority = 25

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.session_id or state.work_item_id)

    async def run(self, state: ContextState) -> ContextState:
        lines: list[str] = []

        # ── Pending approvals ────────────────────────────────────
        approvals = await self._fetch_pending_approvals(state)
        if approvals:
            lines.append("[PENDING_STATE — Approvals waiting review]")
            for a in approvals:
                lines.append(f"  - Approval {a.get('id', '?')}: {a.get('title', 'sem título')} "
                             f"(type={a.get('approval_type', '?')}, status={a.get('status', '?')})")
            lines.append("")

        # ── WI blocked ──────────────────────────────────────────
        wi_blocked = await self._fetch_wi_blocked(state)
        if wi_blocked:
            lines.append("[PENDING_STATE — Work Item blocked]")
            for b in wi_blocked:
                lines.append(f"  - {b}")
            lines.append("")

        # ── Open team requests ──────────────────────────────────
        team_reqs = await self._fetch_team_requests(state)
        if team_reqs:
            lines.append("[PENDING_STATE — Open team requests]")
            for r in team_reqs:
                lines.append(f"  - {r}")
            lines.append("")

        if not lines:
            state.meta["pending_state_injected"] = False
            return state

        section = PromptSection(
            layer="L4",
            kind="pending_state",
            content="\n".join(lines),
            provenance="work_queue:approvals+team_requests",
            trust_level="operational",
            char_budget=len("\n".join(lines)),
        )
        state.sections.append(section)
        state.meta["pending_state_injected"] = True
        state.meta["pending_approvals_count"] = len(approvals)

        return state

    async def _fetch_pending_approvals(self, state: ContextState) -> list[dict]:
        """Fetch approvals awaiting review for this session/WI."""
        import asyncio

        try:
            return await asyncio.to_thread(
                _query_pending_approvals,
                state.session_id,
                state.work_item_id,
                state.tenant_id,
                state.user_id,
            )
        except Exception:
            logger.debug("Pending approvals lookup failed", exc_info=True)
            return []

    async def _fetch_wi_blocked(self, state: ContextState) -> list[str]:
        """Check if work item is blocked by policy."""
        import asyncio

        if not state.work_item_id:
            return []
        try:
            return await asyncio.to_thread(
                _query_wi_blockers,
                state.work_item_id,
                state.tenant_id,
            )
        except Exception:
            logger.debug("WI blocker lookup failed", exc_info=True)
            return []

    async def _fetch_team_requests(self, state: ContextState) -> list[str]:
        """Fetch open team requests (lead_decision, policy_exception)."""
        import asyncio

        try:
            return await asyncio.to_thread(
                _query_team_requests,
                state.tenant_id,
                state.user_id,
            )
        except Exception:
            logger.debug("Team requests lookup failed", exc_info=True)
            return []


# ═══════════════════════════════════════════════════════════════
# DB query helpers (synchronous, run via asyncio.to_thread)
# ═══════════════════════════════════════════════════════════════

def _query_pending_approvals(
    session_id: str | None,
    work_item_id: str | None,
    tenant_id: str,
    user_id: str,
) -> list[dict]:
    """Query approvals awaiting review from PG."""
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            conditions = ["a.tenant_id = %s", "a.status = 'pending'"]
            params: list = [tenant_id]

            if session_id:
                conditions.append("a.session_id = %s")
                params.append(session_id)
            elif work_item_id:
                conditions.append("a.work_item_id = %s")
                params.append(work_item_id)

            where = " AND ".join(conditions)
            cur.execute(
                f"SELECT a.id, a.title, a.approval_type, a.status "
                f"FROM approvals a WHERE {where} ORDER BY a.created_at DESC LIMIT 5",
                params,
            )
            rows = cur.fetchall()
            return [
                {"id": str(r[0]), "title": str(r[1] or ""),
                 "approval_type": str(r[2] or ""), "status": str(r[3] or "")}
                for r in rows
            ]
    except Exception:
        return []


def _query_wi_blockers(work_item_id: str, tenant_id: str) -> list[str]:
    """Check if work item has policy blockers."""
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT reason FROM wi_blockers "
                "WHERE work_item_id = %s AND tenant_id = %s AND resolved = false",
                (work_item_id, tenant_id),
            )
            return [str(r[0]) for r in cur.fetchall()]
    except Exception:
        return []


def _query_team_requests(tenant_id: str, user_id: str) -> list[str]:
    """Query open team requests."""
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT type, title FROM team_requests "
                "WHERE tenant_id = %s AND status = 'open' "
                "ORDER BY created_at DESC LIMIT 5",
                (tenant_id,),
            )
            rows = cur.fetchall()
            return [f"{r[0]}: {r[1]}" for r in rows]
    except Exception:
        return []
