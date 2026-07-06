"""RetrievalOrchestrator — L5 RAG step with automatic gates.

Parallel retrieval from multiple RAG namespaces (session, document, memory,
product, playbook). Each namespace is controlled by an AutoGate from
ContextPolicy.

Gate semantics:
  - NEVER: skip entirely
  - ALWAYS_IF_SESSION: run if session_id is present
  - IF_ACTIVE_DOC: run if active_document_id is set
  - SEMANTIC_GATE: run retrieval, but only include results with score > threshold
  - INTENT_GATE: only run if the user query matches intent keywords
  - KEYWORD_GATE: only run if literal token overlap exceeds threshold

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §6
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState, PromptSection

logger = logging.getLogger(__name__)

# Timeout per retrieval (ms)
_RETRIEVAL_TIMEOUT_MS = 150

# Char budget for all L5 sections combined
_RAG_CHAR_BUDGET = 6_000

# Semantic score threshold for memory recall
_MEMORY_SCORE_THRESHOLD = 0.35

# Minimum token overlap for keyword-gated retrievals (playbook)
_KEYWORD_OVERLAP_THRESHOLD = 2

# Minimum message count for session RAG
_SESSION_MIN_MESSAGES = 20

# Product intent keywords (from plan §6.2 + expanded)
_PRODUCT_INTENT_KEYWORDS = [
    "centralchat", "central chat", "context engine", "contexto", "pipeline",
    "workspace", "connector", "session", "memória", "memory recall", "skill",
    "config central", "deploy", "docker", "podman", "pgvector",
    "embedding", "approval system", "context policy", "política",
    "assembly", "inference engine", "orchestrator", "orquestrador",
    "cliente central", "cli mode", "solo mode", "team mode", "enterprise",
]

# Playbook token overlap keywords
_PLAYBOOK_KEYWORDS = [
    "playbook", "cookbook", "recipe", "padrão", "pattern",
    "como fazer", "how to", "guia", "guide", "template",
    "exemplo", "example", "best practice", "boa prática",
]


@register_step
class RetrievalOrchestratorStep:
    """Orchestrates parallel RAG retrieval across namespaces.

    Phase: gather (after system layers).
    Priority: 15 (after system layers, before tool selection).
    """

    name = "gather.retrieval"
    phase = Phase.GATHER
    priority = 15

    async def should_run(self, state: ContextState) -> bool:
        # Skip if focus mode or no user text
        if state.focus_mode or not state.user_text.strip():
            return False
        # Skip if no retrieval gate is open
        gates = [
            state.session_rag_gate,
            state.document_rag_gate,
            state.memory_recall_gate,
            state.product_rag_gate,
            state.playbook_gate,
        ]
        return any(g != "never" for g in gates)

    async def run(self, state: ContextState) -> ContextState:
        t0 = time.monotonic()
        tasks: list[asyncio.Task] = []

        # ── Session RAG ─────────────────────────────────────────
        if self._gate_allows_session(state):
            tasks.append(asyncio.create_task(self._retrieve_session(state)))

        # ── Document RAG ────────────────────────────────────────
        if self._gate_allows_document(state):
            tasks.append(asyncio.create_task(self._retrieve_document(state)))

        # ── Memory recall ───────────────────────────────────────
        if self._gate_allows_memory(state):
            tasks.append(asyncio.create_task(self._retrieve_memory(state)))

        # ── Product RAG ─────────────────────────────────────────
        if self._gate_allows_product(state):
            tasks.append(asyncio.create_task(self._retrieve_product(state)))

        # ── Playbook ────────────────────────────────────────────
        if self._gate_allows_playbook(state):
            tasks.append(asyncio.create_task(self._retrieve_playbook(state)))

        if not tasks:
            return state

        # Run all retrievals in parallel with individual timeouts
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful results
        sections: list[PromptSection] = []
        hit_counts: dict[str, int] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Retrieval failed: %s", result)
                continue
            if result is None:
                continue
            if isinstance(result, list):
                sections.extend(result)
            elif isinstance(result, PromptSection):
                sections.append(result)

        # Apply char budget — truncate if needed
        total_chars = sum(len(s.content) for s in sections)
        if total_chars > _RAG_CHAR_BUDGET:
            ratio = _RAG_CHAR_BUDGET / max(total_chars, 1)
            for s in sections:
                max_chars = max(200, int(s.char_budget * ratio)) if s.char_budget else int(len(s.content) * ratio)
                if len(s.content) > max_chars:
                    s.content = s.content[:max_chars] + "\n…"

        # Add sections to state
        state.sections.extend(sections)
        if sections:
            state.layers_applied.append("L5")
            state.recall_count += len(sections)

        state.meta["rag_hit_count"] = hit_counts
        state.meta["rag_build_ms"] = round((time.monotonic() - t0) * 1000, 2)
        state.meta["rag_sections"] = len(sections)

        return state

    # ═══════════════════════════════════════════════════════════
    # Gate logic (§6.2)
    # ═══════════════════════════════════════════════════════════

    def _gate_allows_session(self, state: ContextState) -> bool:
        """Session RAG: ALWAYS_IF_SESSION when session present."""
        if state.session_rag_gate == "never":
            return False
        if not state.session_id:
            return False
        if state.session_rag_gate == "always_if_session":
            return True
        # SEMANTIC_GATE fallback: check message count
        if state.session_rag_gate == "semantic_gate":
            return len(state.history) >= _SESSION_MIN_MESSAGES
        return state.session_rag_gate != "never"

    def _gate_allows_document(self, state: ContextState) -> bool:
        """Document RAG: IF_ACTIVE_DOC when document is set."""
        if state.document_rag_gate == "never":
            return False
        if not state.active_document_id:
            return False
        return state.document_rag_gate in ("if_active_doc", "always_if_session")

    def _gate_allows_memory(self, state: ContextState) -> bool:
        """Memory recall: SEMANTIC_GATE — skip greetings and very short queries."""
        if state.memory_recall_gate == "never":
            return False
        text = state.user_text.strip().lower()

        # Skip greetings and very short queries
        greetings = {"olá", "oi", "hey", "hello", "hi", "bom dia", "boa tarde",
                      "boa noite", "e aí", "iae", "tudo bem", "como estás"}
        if text in greetings or len(text) < 10:
            return False

        if state.memory_recall_gate == "semantic_gate":
            return True
        return state.memory_recall_gate != "never"

    def _gate_allows_product(self, state: ContextState) -> bool:
        """Product RAG: INTENT_GATE — only for product-related queries."""
        if state.product_rag_gate == "never":
            return False
        if state.focus_mode:
            return False

        text = state.user_text.strip().lower()
        if len(text) < 15:
            return False

        if state.product_rag_gate == "intent_gate":
            return any(kw in text for kw in _PRODUCT_INTENT_KEYWORDS)

        return state.product_rag_gate != "never"

    def _gate_allows_playbook(self, state: ContextState) -> bool:
        """Playbook: KEYWORD_GATE — only when token overlap exceeds threshold."""
        if state.playbook_gate == "never":
            return False
        if state.focus_mode:
            return False

        text_tokens = set(state.user_text.strip().lower().split())
        keyword_set = set(_PLAYBOOK_KEYWORDS)
        overlap = len(text_tokens & keyword_set)
        # Also check substring matches
        for kw in _PLAYBOOK_KEYWORDS:
            if kw in state.user_text.lower():
                overlap += 1

        if state.playbook_gate == "keyword_gate":
            return overlap >= _KEYWORD_OVERLAP_THRESHOLD

        return state.playbook_gate != "never"

    # ═══════════════════════════════════════════════════════════
    # Retrieval helpers
    # ═══════════════════════════════════════════════════════════

    async def _retrieve_session(self, state: ContextState) -> list[PromptSection] | None:
        if not state.session_id:
            return None
        try:
            from app.rag import search_session_context

            hits = await asyncio.to_thread(
                search_session_context,
                query=state.user_text,
                chat_session_id=state.session_id,
                tenant_id=state.tenant_id,
                top_k=6,
            )
        except Exception:
            logger.debug("Session RAG failed", exc_info=True)
            return None

        if not hits:
            return None

        parts = ["[CONTEXT_RETRIEVED — session namespace]\n"]
        for h in hits[:6]:
            content = str(getattr(h, "content", "") or "")
            if content.strip():
                parts.append(f"- {content.strip()[:600]}")

        if len(parts) == 1:
            return None

        return [PromptSection(
            layer="L5",
            kind="session_rag",
            content="\n".join(parts),
            provenance="pgvector:session_rag_chunks",
            trust_level="retrieved",
            char_budget=min(len("\n".join(parts)), 3000),
            score=None,
        )]

    async def _retrieve_document(self, state: ContextState) -> list[PromptSection] | None:
        if not state.active_document_id:
            return None
        try:
            from app.rag import search_document_context

            hits = await asyncio.to_thread(
                search_document_context,
                query=state.user_text,
                doc_id=state.active_document_id,
                tenant_id=state.tenant_id,
                top_k=5,
            )
        except Exception:
            logger.debug("Document RAG failed", exc_info=True)
            return None

        if not hits:
            return None

        parts = [f"[DOCUMENT_RAG — excerpts only; doc_id={state.active_document_id}]\n"]
        for h in hits[:5]:
            content = str(getattr(h, "content", "") or "")
            if content.strip():
                parts.append(f"- {content.strip()[:500]}")

        if len(parts) == 1:
            return None

        return [PromptSection(
            layer="L5",
            kind="document_rag",
            content="\n".join(parts),
            provenance=f"pgvector:document_rag_chunks:{state.active_document_id}",
            trust_level="retrieved",
            char_budget=min(len("\n".join(parts)), 2500),
            score=None,
        )]

    async def _retrieve_memory(self, state: ContextState) -> list[PromptSection] | None:
        try:
            from app.rag import embed_local_hash, search_memory

            embedding = embed_local_hash(state.user_text)

            # Use work_item namespace when WI is active (plan §9.4)
            namespace = "user_profile"
            if state.work_item_id:
                namespace = f"work_item:{state.work_item_id}"

            hits = await asyncio.to_thread(
                search_memory,
                namespace=namespace,
                query_embedding=embedding,
                top_k=5,
                tenant_id=state.tenant_id,
            )
        except Exception:
            logger.debug("Memory recall failed", exc_info=True)
            return None

        if not hits:
            return None

        # SEMANTIC_GATE: filter by score threshold
        scores = []
        filtered = []
        for h in hits[:5]:
            score = getattr(h, "score", 0.0) or 0.0
            content = str(getattr(h, "content", "") or "")
            if score >= _MEMORY_SCORE_THRESHOLD and content.strip():
                filtered.append(h)
                scores.append(score)

        if not filtered:
            return None

        parts = ["[MEMORY_RECALL L5]\n"]
        for h in filtered:
            parts.append(f"- {str(getattr(h, 'content', ''))[:400]}")

        if len(parts) == 1:
            return None

        avg_score = sum(scores) / len(scores) if scores else 0.0
        return [PromptSection(
            layer="L5",
            kind="memory_recall",
            content="\n".join(parts),
            provenance="pgvector:memory_items",
            trust_level="retrieved",
            char_budget=min(len("\n".join(parts)), 2000),
            score=round(avg_score, 4),
        )]

    async def _retrieve_product(self, state: ContextState) -> list[PromptSection] | None:
        # INTENT_GATE already checked in _gate_allows_product
        try:
            from app.rag import search_product_context

            hits = await asyncio.to_thread(
                search_product_context,
                query=state.user_text,
                tenant_id=state.tenant_id,
                top_k=4,
            )
        except Exception:
            logger.debug("Product RAG failed", exc_info=True)
            return None

        if not hits:
            return None

        parts = ["[PRODUCT_RAG L5]\n"]
        for h in hits[:4]:
            content = str(getattr(h, "content", "") or "")
            if content.strip():
                parts.append(f"- {content.strip()[:400]}")

        if len(parts) == 1:
            return None

        return [PromptSection(
            layer="L5",
            kind="product_rag",
            content="\n".join(parts),
            provenance="pgvector:product_rag_chunks",
            trust_level="retrieved",
            char_budget=min(len("\n".join(parts)), 2000),
            score=None,
        )]

    async def _retrieve_playbook(self, state: ContextState) -> list[PromptSection] | None:
        """Retrieve playbook snippets matched by token overlap."""
        try:
            from app.playbook import list_playbook_entries_meta

            entries = await asyncio.to_thread(
                list_playbook_entries_meta,
                include_expired=False,
            )
        except Exception:
            logger.debug("Playbook retrieval failed", exc_info=True)
            return None

        if not entries:
            return None

        # Simple token overlap ranking
        text_tokens = set(state.user_text.lower().split())
        scored: list[tuple[Any, int]] = []
        for entry in entries:
            name = str(getattr(entry, "name", "") or "").lower()
            desc = str(getattr(entry, "description", "") or "").lower()
            combined = f"{name} {desc}"
            entry_tokens = set(combined.split())
            overlap = len(text_tokens & entry_tokens)
            if overlap > 0:
                scored.append((entry, overlap))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:3]

        parts = ["[PLAYBOOK L5]\n"]
        for entry, score in top:
            name = str(getattr(entry, "name", "") or "")
            desc = str(getattr(entry, "description", "") or "")
            parts.append(f"- {name}: {desc[:300]}")

        if len(parts) == 1:
            return None

        return [PromptSection(
            layer="L5",
            kind="playbook",
            content="\n".join(parts),
            provenance="pgvector:playbook_entries",
            trust_level="retrieved",
            char_budget=min(len("\n".join(parts)), 1500),
            score=None,
        )]
