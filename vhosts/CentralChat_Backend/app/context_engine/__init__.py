"""ContextEngine — pluggable context assembly pipeline.

Replaces the monolithic ContextPipeline with a step-based architecture.
Each step is a callable registered in STEP_REGISTRY, executed in priority
order within its phase.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §3

Phases:
  resolve  — synchronous, <5ms: resolve session, work item, active doc, policy
  gather   — async parallel, ~120ms budget: system layers, RAG, tool selection
  assemble — synchronous, deterministic: merge, budget, build messages
  post     — background: indexing, compaction checkpoint, audit
"""

from __future__ import annotations

import logging
from typing import Any

from .state import ContextState, PromptSection, TokenBudget
from .registry import (
    STEP_REGISTRY,
    Phase,
    register_step,
    run_phase,
    run_all_phases,
    list_steps,
)

# Auto-import steps so they register themselves
# Resolve (sync, <5ms)
from .steps.resolve import session_history  # noqa: F401
from .steps.resolve import work_item  # noqa: F401
from .steps.resolve import handoff  # noqa: F401
from .steps.resolve import active_document  # noqa: F401
from .steps.resolve import execution_mode  # noqa: F401

# Gather (async parallel, ~120ms)
from .steps.gather import security_anchor  # noqa: F401 — L0 DLP + pre-injection
from .steps.gather import system_layers  # noqa: F401
from .steps.gather import file_lease  # noqa: F401 — L2 file leasing
from .steps.gather import environment_gates  # noqa: F401 — H-6 label scoping
from .steps.gather import retrieval  # noqa: F401
from .steps.gather import pending_state  # noqa: F401
from .steps.gather import tool_selection  # noqa: F401
from .steps.gather import compaction_prep  # noqa: F401

# Assemble (sync, deterministic)
from .steps.assemble import merge_sections  # noqa: F401
from .steps.assemble import token_budget  # noqa: F401
from .steps.assemble import build_messages  # noqa: F401

# Post (background)
from .steps.post import session_index  # noqa: F401
from .steps.post import async_checkpoint  # noqa: F401
from .steps.post import audit_emit  # noqa: F401

logger = logging.getLogger(__name__)


async def assemble_context(
    *,
    request_id: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    tenant_id: str = "default",
    user_id: str = "",
    role: str = "developer",
    session_id: str | None = None,
    work_item_id: str | None = None,
    active_document_id: str | None = None,
    handoff_from_session_id: str | None = None,
    session_mode: str = "continue",
    agent_name: str | None = None,
    mode: str = "web",
    connector_alive: bool = False,
    connector_id: str | None = None,
    workspace_path: str | None = None,
    focus_mode: bool = False,
) -> ContextState:
    """Assemble context for a single assistant turn.

    This is the main entry point. It creates a ContextState,
    runs all phases (resolve → gather → assemble → post),
    and returns the final state with assembled messages.

    The caller reads state.messages and state.tools to send
    to the LLM.
    """
    state = ContextState(
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        session_id=session_id,
        work_item_id=work_item_id,
        active_document_id=active_document_id,
        handoff_from_session_id=handoff_from_session_id,
        session_mode=session_mode,
        agent_name=agent_name,
        mode=mode,
        connector_alive=connector_alive,
        connector_id=connector_id,
        workspace_path=workspace_path,
        user_text=user_text,
        history=list(history or []),
        focus_mode=focus_mode,
    )

    # ── Apply ContextPolicy: resolve and set gates on state ──
    from .policy import resolve_policy

    policy = resolve_policy(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        execution_mode=mode,
        chat_session_id=session_id,
        work_item_id=work_item_id,
        active_document_id=active_document_id,
        force_focus=focus_mode,
    )

    # Log deprecated flags if any were explicitly set (non-default values)
    if any(v for v in policy._deprecated_flags.values()):
        logger.warning(
            "deprecated HTTP context flags in request_id=%s: %s — these are ignored. "
            "Context is now fully server-driven via ContextPolicy.",
            request_id,
            {k: v for k, v in policy._deprecated_flags.items() if v},
        )

    # Map policy gates → state flags
    state.focus_mode = policy.focus_mode
    state.dlp_enabled = policy.dlp_enabled
    state.session_rag_gate = policy.session_rag.value
    state.document_rag_gate = policy.document_rag.value
    state.memory_recall_gate = policy.memory_recall.value
    state.product_rag_gate = policy.product_rag.value
    state.playbook_gate = policy.playbook.value
    state.role_tool_allowlist = policy.role_tool_allowlist

    # Store policy summary for ui_trace
    state.meta["context_policy_summary_pt"] = _build_summary(policy)

    state = await run_all_phases(state)

    # ── Emit Prometheus metrics ──
    try:
        from .metrics import emit_step_metrics

        emit_step_metrics(state)
    except Exception:
        logger.debug("Metrics emission failed", exc_info=True)

    logger.info(
        "context_engine assembled request_id=%s layers=%s build_ms=%.1f tools=%d mode=%s",
        request_id,
        "+".join(state.layers_applied) if state.layers_applied else "none",
        state.build_ms,
        len(state.tools),
        mode,
    )

    return state


def _build_summary(policy) -> str:
    """Build a one-line policy summary for logging (avoid circular import)."""
    from .policy import build_policy_summary_pt

    return build_policy_summary_pt(policy)


def assemble_context_sync(
    *,
    request_id: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    tenant_id: str = "default",
    user_id: str = "",
    role: str = "developer",
    session_id: str | None = None,
    work_item_id: str | None = None,
    active_document_id: str | None = None,
    handoff_from_session_id: str | None = None,
    session_mode: str = "continue",
    agent_name: str | None = None,
    mode: str = "web",
    connector_alive: bool = False,
    connector_id: str | None = None,
    workspace_path: str | None = None,
    focus_mode: bool = False,
) -> ContextState:
    """Synchronous wrapper for assemble_context().

    Use this when the caller is not in an async context
    (e.g., the existing ContextPipeline.assemble() wrapper).
    """
    import asyncio

    return asyncio.run(assemble_context(
        request_id=request_id,
        user_text=user_text,
        history=history,
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        session_id=session_id,
        work_item_id=work_item_id,
        active_document_id=active_document_id,
        handoff_from_session_id=handoff_from_session_id,
        session_mode=session_mode,
        agent_name=agent_name,
        mode=mode,
        connector_alive=connector_alive,
        connector_id=connector_id,
        workspace_path=workspace_path,
        focus_mode=focus_mode,
    ))


__all__ = [
    "ContextState",
    "PromptSection",
    "TokenBudget",
    "STEP_REGISTRY",
    "ContextStep",
    "Phase",
    "register_step",
    "run_phase",
    "run_all_phases",
    "list_steps",
    "assemble_context",
    "assemble_context_sync",
]
