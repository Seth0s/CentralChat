"""Compaction prep step — unified compaction with tiktoken-aware logic.

Absorbs the legacy ContextWindowManager and CompactionService into
a single compaction policy using tiktoken for accurate token counting.

Phase: gather.
Priority: 30.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §7.1
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)

# Compaction defaults (aligned with ContextPolicy)
_MAX_MESSAGES = 64
_KEEP_RECENT = 20
_SUMMARY_MAX_CHARS = 1200
_COMPACT_THRESHOLD_TOKENS = 32_000


@register_step
class CompactionPrepStep:
    """Compacts session history using tiktoken-aware token budget.

    Strategy:
    1. Count tokens in history
    2. If under threshold: no compaction
    3. If over threshold: keep recent N messages verbatim, summarize older
    4. Apply [SUMMARY vN] prefix if summarization was used

    Phase: gather.
    Priority: 30.
    """

    name = "gather.compaction_prep"
    phase = Phase.GATHER
    priority = 30

    async def should_run(self, state: ContextState) -> bool:
        return bool(state.history)

    async def run(self, state: ContextState) -> ContextState:
        from app.context_engine.token_counter import get_token_counter

        counter = get_token_counter()
        history = state.history
        before_count = len(history)
        before_tokens = counter.count_messages(history)

        # ── Check if compaction is needed ───────────────────────
        threshold = self._get_threshold(state)
        if before_tokens <= threshold and before_count <= _MAX_MESSAGES:
            # No compaction needed
            state.meta["token_accounting"] = {
                "verbatim_tokens_before": before_tokens,
                "verbatim_tokens_after": before_tokens,
                "compacted": False,
                "compaction_mode": "none",
            }
            return state

        # ── Compaction needed ────────────────────────────────────
        recent = history[-_KEEP_RECENT:] if _KEEP_RECENT > 0 else []
        older = history[: max(0, len(history) - len(recent))]

        if not older:
            # Just truncate to max messages
            truncated = history[-_MAX_MESSAGES:]
            after_tokens = counter.count_messages(truncated)
            state.history = list(truncated)
            state.session_truncated = True
            state.meta["token_accounting"] = {
                "verbatim_tokens_before": before_tokens,
                "verbatim_tokens_after": after_tokens,
                "compacted": True,
                "compaction_mode": "truncate",
            }
            if "L5" not in state.layers_applied:
                state.layers_applied.append("L5")
            return state

        # ── Progressive summarization ────────────────────────────
        summary_text, summary_version = await self._summarize(
            older, state.session_id, state.tenant_id, state.request_id,
        )

        result_messages: list[dict[str, str]] = []
        if summary_text:
            result_messages.append({
                "role": "system",
                "content": f"[SUMMARY v{summary_version}]\n{summary_text}",
            })
        result_messages.extend(recent)

        after_tokens = counter.count_messages(result_messages)
        state.history = result_messages
        state.session_truncated = True
        state.meta["token_accounting"] = {
            "verbatim_tokens_before": before_tokens,
            "verbatim_tokens_after": after_tokens,
            "compacted": True,
            "compaction_mode": "progressive_summarize",
            "summary_version": summary_version,
            "summary_chars": len(summary_text or ""),
        }
        if "L5" not in state.layers_applied:
            state.layers_applied.append("L5")

        return state

    def _get_threshold(self, state: ContextState) -> int:
        """Get the compaction token threshold."""
        try:
            from app.context._core import load_context_settings
            return load_context_settings().compact_threshold_tokens
        except Exception:
            return _COMPACT_THRESHOLD_TOKENS

    @staticmethod
    async def _summarize(
        older: list[dict[str, str]],
        session_id: str | None,
        tenant_id: str,
        request_id: str,
    ) -> tuple[str | None, int | None]:
        """Progressively summarize older messages."""
        import asyncio

        prev_summary, prev_version = await asyncio.to_thread(
            _load_summary, session_id, tenant_id,
        )

        text = _msgs_to_text(older)
        if prev_summary:
            text = f"[Resumo anterior v{prev_version}]\n{prev_summary}\n\n[Novas mensagens]\n{text}"

        try:
            from app.clients import call_llm

            summary = await asyncio.to_thread(
                call_llm,
                f"Resume esta conversa em português (máx 300 palavras). "
                f"Foca nos factos, decisões técnicas, ficheiros modificados.\n\n{text}",
                history=[],
                profile="balanced",
                model_override=None,
                allowlist_mode="modality",
            )
            summary = summary.strip()[: _SUMMARY_MAX_CHARS]
        except Exception:
            logger.debug("Summarization failed for session=%s", session_id, exc_info=True)
            return prev_summary, prev_version

        if not summary:
            return prev_summary, prev_version

        new_version = (prev_version or 0) + 1
        await asyncio.to_thread(_save_summary, session_id, tenant_id, new_version, summary)
        return summary, new_version


def _load_summary(session_id: str | None, tenant_id: str) -> tuple[str | None, int | None]:
    if not session_id:
        return None, None
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT summary_text, version FROM session_summaries "
                "WHERE tenant_id=%s AND session_id=%s ORDER BY version DESC LIMIT 1",
                (tenant_id, session_id),
            )
            row = cur.fetchone()
            if row:
                return str(row[0]), int(row[1])
    except Exception:
        logger.debug("Failed to load summary for session=%s", session_id, exc_info=True)
    return None, None


def _save_summary(session_id: str | None, tenant_id: str, version: int, text: str) -> None:
    if not session_id:
        return
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO session_summaries (tenant_id, session_id, version, summary_text, provenance) "
                "VALUES (%s, %s, %s, %s, 'context_engine') "
                "ON CONFLICT (tenant_id, session_id, version) DO UPDATE "
                "SET summary_text = EXCLUDED.summary_text, provenance = EXCLUDED.provenance",
                (tenant_id, session_id, version, text),
            )
    except Exception:
        logger.debug("Failed to save summary for session=%s", session_id, exc_info=True)


def _msgs_to_text(messages: list[dict[str, str]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = str(m.get("content", ""))[:500]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)
