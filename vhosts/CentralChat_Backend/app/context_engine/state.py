"""ContextEngine state types — ContextState, PromptSection, TokenBudget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ═══════════════════════════════════════════════════════════════
# PromptSection — uniform context injection block
# ═══════════════════════════════════════════════════════════════

@dataclass
class PromptSection:
    """A single injected context block with provenance tracking.

    Every section has a trust_level so the UI can differentiate
    curated (L0-L4) from retrieved (L5) from user-uploaded content.
    """

    layer: str
    """Layer identifier: L0, L1, L2, L3, L4, L5, L6, L7."""

    kind: str
    """Section kind: session_rag, document_rag, work_item, pending_state, etc."""

    content: str
    """The text content to inject (may be truncated by budget)."""

    provenance: str
    """Where this came from: pgvector:product_rag_chunks, work_items, git, etc."""

    trust_level: Literal["curated", "retrieved", "user_upload", "operational"]
    """Trust classification for UI display and security boundaries."""

    char_budget: int = 0
    """Max characters allocated to this section (0 = budget not applied yet)."""

    score: float | None = None
    """Relevance score from retrieval (None for deterministic sections)."""


# ═══════════════════════════════════════════════════════════════
# TokenBudget
# ═══════════════════════════════════════════════════════════════

@dataclass
class TokenBudget:
    """Token allocation across context layers.

    Calculated before assembly to ensure total stays under
    max_context_tokens. L6 (session_window) gets whatever remains
    after L0-L5 and L7 are allocated.
    """

    max_total: int = 128_000
    """Hard cap on total context tokens."""

    # Allocated
    l0_l4: int = 0
    """Tokens used by deterministic layers (L0-L4)."""

    l5_rag: int = 0
    """Tokens used by retrieval sections (L5)."""

    l6_window: int = 0
    """Tokens remaining for session window (L6)."""

    l7_tools: int = 0
    """Tokens used by tool schemas (L7)."""

    # Accounting
    reserved_safety: int = 2_000
    """Safety margin reserved for model response."""

    def available_for_l6(self) -> int:
        """Tokens available for session window after all other layers."""
        used = self.l0_l4 + self.l5_rag + self.l7_tools + self.reserved_safety
        return max(0, self.max_total - used)

    def is_over_budget(self) -> bool:
        """True if total allocation exceeds max."""
        return (self.l0_l4 + self.l5_rag + self.l6_window +
                self.l7_tools + self.reserved_safety) > self.max_total


# ═══════════════════════════════════════════════════════════════
# ContextState — the state object passed through all steps
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextState:
    """Mutable state carried through the context assembly pipeline.

    Each step reads and mutates this state. The final state
    is used to build the messages array sent to the LLM.
    """

    # ── Request identity ───────────────────────────────────────
    request_id: str = ""
    tenant_id: str = "default"
    user_id: str = ""
    role: str = "developer"
    """RBAC role: developer, reviewer, lead, auditor, admin."""

    # ── Session ────────────────────────────────────────────────
    session_id: str | None = None
    work_item_id: str | None = None
    active_document_id: str | None = None
    handoff_from_session_id: str | None = None
    session_mode: str = "continue"
    """Session mode: continue (same session), fork (new context), observe (read-only)."""
    agent_name: str | None = None
    mode: str = "web"
    """Execution mode: web, cli."""

    # ── Connector ──────────────────────────────────────────────
    connector_alive: bool = False
    connector_id: str | None = None
    workspace_path: str | None = None

    # ── User input ─────────────────────────────────────────────
    user_text: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    """Raw history from the request (role + content dicts)."""

    # ── Policy ─────────────────────────────────────────────────
    focus_mode: bool = False
    dlp_enabled: bool = True
    session_rag_gate: str = "never"
    document_rag_gate: str = "never"
    memory_recall_gate: str = "never"
    product_rag_gate: str = "never"
    playbook_gate: str = "never"
    role_tool_allowlist: frozenset = field(default_factory=frozenset)
    """RBAC: tools allowed for this role. Empty = all allowed."""

    # ── Accumulated output ─────────────────────────────────────
    sections: list[PromptSection] = field(default_factory=list)
    """Ordered list of PromptSections to inject (L0 → L7)."""

    tools: list[dict[str, Any]] = field(default_factory=list)
    """OpenAI tool schemas selected for this turn."""

    tool_catalog: list[str] = field(default_factory=list)
    """Lightweight tool name catalog for [TOOLS] block."""

    messages: list[dict[str, str]] = field(default_factory=list)
    """Final assembled messages (system layers + compacted history + user)."""

    # ── Budget ─────────────────────────────────────────────────
    budget: TokenBudget = field(default_factory=TokenBudget)

    # ── Meta ───────────────────────────────────────────────────
    meta: dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata passed between steps (injection_meta)."""

    layers_applied: list[str] = field(default_factory=list)
    """Layer IDs that were successfully applied (e.g. ['L0','L1','L3','L5'])."""

    build_ms: float = 0.0
    """Total build time in milliseconds."""

    session_truncated: bool = False
    """True if session history was compacted."""

    recall_count: int = 0
    """Number of RAG/memory items recalled."""

    # ── Temporary state (step-private) ─────────────────────────
    _private: dict[str, Any] = field(default_factory=dict)
    """Scratch space for steps to communicate without polluting meta."""
