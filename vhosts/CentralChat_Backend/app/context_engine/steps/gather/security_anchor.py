"""L0 security anchor step — DLP scan + pre-injection prompt.

Phase: gather (runs before system layers).
Priority: 5 (first gather step).

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §4 (L0 security_anchor)
"""

from __future__ import annotations

import logging

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)


@register_step
class SecurityAnchorStep:
    """DLP pre-prompt scan + institutional pre-injection (L0).

    Runs before all other gather steps. Blocks the turn if DLP
    detects secrets/PII in the user prompt.

    Also injects the institutional pre-injection prompt file if
    configured and not in focus mode.

    Phase: gather.
    Priority: 5 (first gather step, before system layers).
    """

    name = "gather.security_anchor"
    phase = Phase.GATHER
    priority = 5

    async def should_run(self, state: ContextState) -> bool:
        return True  # Always runs — security is non-negotiable

    async def run(self, state: ContextState) -> ContextState:
        # ── DLP scan ─────────────────────────────────────────────
        if state.dlp_enabled and state.user_text.strip():
            self._run_dlp(state)

        # ── Pre-injection ────────────────────────────────────────
        if not state.focus_mode:
            self._inject_pre_prompt(state)

        return state

    def _run_dlp(self, state: ContextState) -> None:
        """Scan user text for secrets/PII. Block if found."""
        try:
            from app.shared.dlp_scanner import scan_prompt_text

            result = scan_prompt_text(
                state.user_text,
                tenant_id=state.tenant_id,
            )
            if not result.allowed:
                logger.warning(
                    "DLP blocked request_id=%s hits=%s",
                    state.request_id,
                    result.hits,
                )
                # Mark as blocked — caller should reject the turn
                state.meta["dlp_blocked"] = True
                state.meta["dlp_hits"] = list(result.hits)
                state.meta["dlp_message_pt"] = result.message_pt
                return
        except Exception:
            logger.debug("DLP scan failed", exc_info=True)

        state.meta["dlp_passed"] = True

    def _inject_pre_prompt(self, state: ContextState) -> None:
        """Load and inject institutional pre-injection prompt."""
        try:
            from app.config import (CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED,
                                    CENTRAL_FOCUS_MODE)

            if not CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED or CENTRAL_FOCUS_MODE:
                return

            from app.shared.system_prompt_loader import (
                build_system_prompt_injection_messages,
            )

            msgs, audit = build_system_prompt_injection_messages()
            if not msgs:
                return

            # Add messages as L0 sections (injected before L1 system layers)
            for msg in msgs:
                state.sections.append(PromptSection(
                    layer="L0",
                    kind="pre_injection",
                    content=msg.get("content", ""),
                    provenance="file:system_prompt_injection",
                    trust_level="curated",
                    char_budget=len(msg.get("content", "")),
                ))

            state.meta["L0_pre_injection"] = audit
            state.layers_applied.append("L0")

        except Exception:
            logger.debug("L0 pre-injection failed", exc_info=True)
