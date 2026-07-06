"""ContextPolicy — server-side policy for context assembly.

Replaces the scattered include_* HTTP flags with a single resolved
policy object that the ContextEngine consumes.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §5

Transition mode (current):
  - resolve_policy() reads env vars + request flags
  - No tenant-level PG policy table yet
  - Flags are accepted but policy takes precedence

Target mode (future):
  - resolve_policy() reads from PG tenant_policies table
  - Per-tenant overrides with optimistic concurrency
  - Role-scoped (RBAC → tool allowlist)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# AutoGate — automatic context inclusion decisions
# ═══════════════════════════════════════════════════════════════

class AutoGate(str, Enum):
    """Automatic gate logic for context retrieval layers.

    NEVER = never include (e.g. focus mode, empty session).
    ALWAYS_IF_SESSION = include when chat_session_id is present.
    IF_ACTIVE_DOC = include when active_document_id is set on session/WI.
    SEMANTIC_GATE = include when query semantically matches (score > threshold).
    INTENT_GATE = include when intent keywords match.
    KEYWORD_GATE = include when literal token overlap exceeds threshold.
    """

    NEVER = "never"
    ALWAYS_IF_SESSION = "always_if_session"
    IF_ACTIVE_DOC = "if_active_doc"
    SEMANTIC_GATE = "semantic_gate"
    INTENT_GATE = "intent_gate"
    KEYWORD_GATE = "keyword_gate"

    def is_automatic(self) -> bool:
        """True when the gate is fully automatic (no user flag needed)."""
        return self in (
            AutoGate.ALWAYS_IF_SESSION,
            AutoGate.IF_ACTIVE_DOC,
            AutoGate.SEMANTIC_GATE,
            AutoGate.INTENT_GATE,
            AutoGate.KEYWORD_GATE,
        )


# ═══════════════════════════════════════════════════════════════
# ContextPolicy
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextPolicy:
    """Resolved policy for a single assistant turn.

    All decisions are server-side. The client observes via ui_trace.
    """

    # ── Budget ─────────────────────────────────────────────────

    max_context_tokens: int = 128_000
    """Hard cap on total context tokens (all layers)."""

    rag_char_budget: int = 6_000
    """Max characters for all L5 retrieval sections combined."""

    verbatim_tail_messages: int = 20
    """Number of most recent messages to keep verbatim after compaction."""

    max_tool_schemas: int = 5
    """Max tool schemas to inject (top-N by score)."""

    # ── Retrieval gates ─────────────────────────────────────────

    session_rag: AutoGate = AutoGate.ALWAYS_IF_SESSION
    """Session RAG: recall past facts from the same session."""

    document_rag: AutoGate = AutoGate.IF_ACTIVE_DOC
    """Document RAG: recall excerpts from an indexed document."""

    memory_recall: AutoGate = AutoGate.SEMANTIC_GATE
    """Memory recall: user/team durable facts matched semantically."""

    product_rag: AutoGate = AutoGate.INTENT_GATE
    """Product RAG: platform docs matched by intent keywords."""

    playbook: AutoGate = AutoGate.KEYWORD_GATE
    """Playbook snippets matched by token overlap."""

    # ── Security ───────────────────────────────────────────────

    dlp_enabled: bool = True
    """Run DLP scanner on prompt before injection (L0)."""

    focus_mode: bool = False
    """Kill-switch: zero embeddings/RAG, minimal context."""

    pre_injection_path: str | None = None
    """Path to pre-injection institutional prompt file (L0)."""

    # ── Tool selection ─────────────────────────────────────────

    tool_selection: Literal["rag", "keyword", "full"] = "keyword"
    """Tool selection strategy: rag (vector), keyword (current), full (all)."""

    role_tool_allowlist: frozenset[str] = field(default_factory=frozenset)
    """RBAC: tools allowed for this role. Empty = all allowed."""

    # ── Role context ───────────────────────────────────────────

    role: str = "developer"
    """RBAC role: developer, reviewer, lead, auditor, admin."""

    work_item_id: str | None = None
    """Active work item ID for L2 injection."""

    active_document_id: str | None = None
    """Active document ID for document RAG gate."""

    # ── Deprecated flags (transition) ──────────────────────────

    _deprecated_flags: dict[str, Any] = field(default_factory=dict)
    """Legacy HTTP flags that were ignored. Logged for deprecation audit."""


# ═══════════════════════════════════════════════════════════════
# resolve_policy()
# ═══════════════════════════════════════════════════════════════

def resolve_policy(
    *,
    tenant_id: str = "default",
    user_id: str = "",
    role: str = "developer",
    execution_mode: str = "web",
    chat_session_id: str | None = None,
    work_item_id: str | None = None,
    active_document_id: str | None = None,
    # ── Legacy flags (transition — logged, not used for decisions) ─
    include_long_session_memory: bool = False,
    include_memory_recall: bool = False,
    include_document_rag: bool = False,
    include_session_rag: bool = True,
    include_playbook: bool = False,
    include_host_context: bool = False,
    include_capability_digest: bool = False,
    # ── Overrides ─
    force_focus: bool = False,
) -> ContextPolicy:
    """Resolve context policy for a turn.

    Transition mode: reads env vars + computes gates automatically.
    Legacy flags are recorded in _deprecated_flags for audit but
    do NOT drive decisions.

    Target mode: reads from PG tenant_policies table (future).
    """
    from app import config as cfg

    # ── Focus mode (kill-switch) ───────────────────────────────
    focus = bool(force_focus or cfg.CENTRAL_FOCUS_MODE)

    # ── DLP ────────────────────────────────────────────────────
    dlp = not focus  # DLP always on unless focus mode

    # ── Pre-injection path ─────────────────────────────────────
    pre_path: str | None = None
    if cfg.PRE_INJECTION_ENABLED and not focus:
        pre_path = cfg.PRE_INJECTION_FILE_PATH or None

    # ── Retrieval gates ────────────────────────────────────────

    # Session RAG: always if session present (unless focus)
    if focus:
        session_rag = AutoGate.NEVER
    elif chat_session_id:
        session_rag = AutoGate.ALWAYS_IF_SESSION
    else:
        session_rag = AutoGate.NEVER

    # Document RAG: only if active document set
    if focus:
        document_rag = AutoGate.NEVER
    elif active_document_id:
        document_rag = AutoGate.IF_ACTIVE_DOC
    else:
        document_rag = AutoGate.NEVER

    # Memory recall: semantic gate (future — for now, gate on session presence)
    if focus:
        memory_recall = AutoGate.NEVER
    elif chat_session_id:
        memory_recall = AutoGate.SEMANTIC_GATE
    else:
        memory_recall = AutoGate.NEVER

    # Product RAG: intent gate (future — for now, enabled if not focus)
    if focus:
        product_rag = AutoGate.NEVER
    elif cfg.CENTRAL_PRODUCT_RAG_ENABLED:
        product_rag = AutoGate.INTENT_GATE
    else:
        product_rag = AutoGate.NEVER

    # Playbook: keyword gate
    if focus:
        playbook = AutoGate.NEVER
    else:
        playbook = AutoGate.KEYWORD_GATE

    # ── Tool selection ─────────────────────────────────────────
    # For now, keep the current keyword-based selection
    tool_selection: Literal["rag", "keyword", "full"] = "keyword"

    # ── Role tool allowlist ────────────────────────────────────
    role_allowlist: frozenset[str] = frozenset()
    if role == "auditor":
        # Auditors get zero write tools
        role_allowlist = frozenset({
            "memory", "session_search", "clarify", "web_search",
        })
    elif role == "reviewer":
        # Reviewers: read-only inspection
        role_allowlist = frozenset({
            "memory", "session_search", "clarify",
            "read_file", "search_files", "web_search",
        })

    # ── Budget ─────────────────────────────────────────────────
    max_tokens = 128_000
    rag_budget = 6_000
    verbatim_tail = 20
    max_tools = 5

    # ── Tenant-level policy overrides (PG) ─────────────────────
    try:
        from app.onda5_hardening import load_tenant_policy_overrides

        overrides = load_tenant_policy_overrides(tenant_id)
        if overrides:
            if overrides.get("max_context_tokens"):
                max_tokens = overrides["max_context_tokens"]
            if overrides.get("rag_char_budget"):
                rag_budget = overrides["rag_char_budget"]
            if overrides.get("verbatim_tail_messages"):
                verbatim_tail = overrides["verbatim_tail_messages"]
            if overrides.get("max_tool_schemas"):
                max_tools = overrides["max_tool_schemas"]
            if overrides.get("focus_mode") is not None:
                focus = overrides["focus_mode"]
            if overrides.get("dlp_enabled") is not None:
                dlp = overrides["dlp_enabled"]
            logger.debug("Tenant policy overrides applied for %s", tenant_id)
    except Exception:
        logger.debug("Tenant policy overrides failed", exc_info=True)

    # ── Capture deprecated flags ───────────────────────────────
    deprecated = {
        "include_long_session_memory": include_long_session_memory,
        "include_memory_recall": include_memory_recall,
        "include_document_rag": include_document_rag,
        "include_session_rag": include_session_rag,
        "include_playbook": include_playbook,
        "include_host_context": include_host_context,
        "include_capability_digest": include_capability_digest,
    }

    return ContextPolicy(
        max_context_tokens=max_tokens,
        rag_char_budget=rag_budget,
        verbatim_tail_messages=verbatim_tail,
        max_tool_schemas=max_tools,
        session_rag=session_rag,
        document_rag=document_rag,
        memory_recall=memory_recall,
        product_rag=product_rag,
        playbook=playbook,
        dlp_enabled=dlp,
        focus_mode=focus,
        pre_injection_path=pre_path,
        tool_selection=tool_selection,
        role_tool_allowlist=role_allowlist,
        role=role,
        work_item_id=work_item_id,
        active_document_id=active_document_id,
        _deprecated_flags=deprecated,
    )


# ═══════════════════════════════════════════════════════════════
# UI trace helper
# ═══════════════════════════════════════════════════════════════

def build_policy_summary_pt(policy: ContextPolicy) -> str:
    """Human-readable summary (pt-BR) of what the policy decided.

    Used in ui_trace.injection_summary_pt so the user can see
    what the server applied without seeing sensitive system messages.
    """
    parts: list[str] = []

    if policy.focus_mode:
        parts.append("🔒 Modo foco ativo — sem RAG, embeddings, nem contexto alargado.")
        return " ".join(parts)

    # Retrieval gates
    gate_labels = {
        AutoGate.NEVER: "desligado",
        AutoGate.ALWAYS_IF_SESSION: "automático (sessão)",
        AutoGate.IF_ACTIVE_DOC: "automático (doc activo)",
        AutoGate.SEMANTIC_GATE: "gate semântico",
        AutoGate.INTENT_GATE: "gate de intenção",
        AutoGate.KEYWORD_GATE: "gate de keywords",
    }

    retrievals = []
    for name, gate in [
        ("RAG sessão", policy.session_rag),
        ("RAG documento", policy.document_rag),
        ("memória", policy.memory_recall),
        ("RAG produto", policy.product_rag),
        ("playbook", policy.playbook),
    ]:
        if gate != AutoGate.NEVER:
            retrievals.append(f"{name}={gate_labels.get(gate, gate.value)}")

    if retrievals:
        parts.append(f"Contexto automático: {', '.join(retrievals)}.")

    if policy.dlp_enabled:
        parts.append("DLP activo.")

    if policy.role_tool_allowlist:
        parts.append(f"Tools scoped ao papel {policy.role}.")

    if not parts:
        parts.append("Contexto mínimo (sem RAG, sem ferramentas especiais).")

    return " ".join(parts)
