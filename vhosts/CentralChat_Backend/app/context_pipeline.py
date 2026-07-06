"""
ContextPipeline — sistema único de montagem de contexto.

Inclui: pipeline, tool registry, tool injector, context window manager.
Design doc: docs/CONTEXT_SYSTEM_REDESIGN.md
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.shared.context_manager import ContextStats

logger = logging.getLogger(__name__)

# chars/4 — substituir por tiktoken quando disponível
_CHARS_PER_TOKEN = 4


# ═══════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════

@dataclass
class AssembledContext:
    """Resultado da montagem de contexto."""

    injected_history: list[dict[str, str]]
    ctx_stats: ContextStats
    session_truncated: bool
    recall_count: int
    injection_meta: dict[str, Any]
    openai_tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SystemLayers:
    """Camadas de sistema MVP (L1–L4) + metadados."""

    messages: list[dict[str, str]] = field(default_factory=list)
    agent_name: str = ""
    skill_names: list[str] = field(default_factory=list)
    build_ms: float = 0.0
    layers_applied: list[str] = field(default_factory=list)
    layer_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompactionResult:
    """Resultado da compactação de histórico."""

    messages: list[dict[str, str]]
    stats: ContextStats
    truncated: bool
    summary_applied: str | None = None
    summary_version: int | None = None


# ═══════════════════════════════════════════
# TOOL REGISTRY (inline)
# ═══════════════════════════════════════════

# Trigger map and category derivation moved to app/tool_catalog.py
# Import from there to avoid duplication
from app.tool_catalog import TRIGGER_MAP as _TRIGGER_MAP, derive_category as _derive_category  # noqa: E402


# ═══════════════════════════════════════════
# TOOL INJECTOR (inline)
# ═══════════════════════════════════════════

class ToolInjector:
    """RAG-driven tool selection + schema tracking."""

    # Class-level constants sourced from tool_catalog
    from app.tool_catalog import (  # noqa: E402
        TIER_0 as _T0,
        DELEGATED_TOOLS as _DLG,
        ALWAYS_AVAILABLE_TOOLS as _ALW,
    )
    TIER_0: set[str] = _T0
    DELEGATED: set[str] = _DLG
    ALWAYS_AVAILABLE: set[str] = _ALW

    def __init__(self) -> None:
        self._active: dict[str, _InjectionState] = {}
        self._turn: int = 0
        self._registry: dict[str, dict[str, Any]] = {}
        self._tool_names: list[str] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        from app.tools import _TOOL_SPECS

        for name, spec in _TOOL_SPECS.items():
            desc = spec.get("plan_description_pt", "") or spec.get("protocol_hint_en", "")
            args_schema = spec.get("arguments_schema", {"type": "object", "properties": {}})
            triggers = list(_TRIGGER_MAP.get(name, []))
            # extrai verbos PT da descrição
            for v in re.findall(r"\b([a-zà-ú]{4,}r)\b", desc.lower()):
                if v not in triggers:
                    triggers.append(v)
            triggers = triggers[:15]
            category = _derive_category(name)
            self._registry[name] = {
                "desc": desc, "schema": {
                    "type": "function",
                    "function": {"name": name, "description": desc, "parameters": args_schema},
                },
                "triggers": triggers, "category": category,
            }
        self._tool_names = sorted(self._registry.keys())
        self._loaded = True

    def select_and_inject(
        self, user_text: str, history: list[dict[str, str]],
        current_messages: list[dict[str, str]], *,
        connector_alive: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        self._ensure_loaded()
        self._turn += 1

        # Filtrar tools disponíveis (DELEGATED só com connector, ALWAYS_AVAILABLE sempre)
        available = {
            name for name in self._tool_names
            if name in self.ALWAYS_AVAILABLE or name not in self.DELEGATED or connector_alive
        }

        # Score (só tools disponíveis)
        context = " ".join(h.get("content", "") for h in history[-3:] if h.get("role") in ("user", "assistant"))
        full = f"{context} {user_text}".lower()
        scored: list[tuple[str, float]] = []
        for name, entry in self._registry.items():
            if name not in available:
                continue
            s = sum(0.3 for t in entry["triggers"] if t.lower() in full)
            if s > 0:
                scored.append((name, min(s, 1.0)))
        scored.sort(key=lambda x: x[1], reverse=True)

        selected = {n for n in self.TIER_0 if n in available}
        for name, score in scored[:5]:
            if score > 0.15:
                selected.add(name)

        to_inject: set[str] = set()
        for name in selected:
            if name not in self._active or not self._marker_in_context(name, current_messages):
                to_inject.add(name)
                if name in self._active:
                    del self._active[name]

        openai_tools = [self._registry[n]["schema"] for n in to_inject if n in self._registry]
        for name in to_inject:
            self._active[name] = _InjectionState(name, self._turn, f"{name}_{self._turn}")

        # Catálogo: só tools disponíveis
        catalog = sorted(available)
        return openai_tools, catalog

    def _marker_in_context(self, tool_name: str, messages: list[dict[str, str]]) -> bool:
        if tool_name not in self._active:
            return False
        marker = f"[TOOL_SCHEMA:id={self._active[tool_name].marker_id}|tool={tool_name}]"
        for msg in reversed(messages):
            if marker in str(msg.get("content", "")):
                return True
        return False

    def get_active_count(self) -> int:
        return len(self._active)


@dataclass
class _InjectionState:
    tool_name: str
    injected_at_turn: int
    marker_id: str


# ═══════════════════════════════════════════
# CONTEXT WINDOW MANAGER (inline)
# ═══════════════════════════════════════════

class ContextWindowManager:
    """Gestão adaptativa de janela de contexto com summarization progressiva."""

    MAX_MESSAGES = 64
    KEEP_RECENT = 20
    SUMMARY_MAX_CHARS = 1200

    def __init__(self) -> None:
        pass

    def compact(
        self, history: list[dict[str, str]], *,
        session_id: str | None = None,
        tenant_id: str = "default",
        request_id: str = "",
        available_tokens: int | None = None,
    ) -> CompactionResult:
        before_count = len(history)
        before_chars = sum(len(m.get("content", "")) for m in history)

        token_budget_meta: dict[str, Any] = {}
        try:
            from app.context._core import TokenBudgetAllocator, load_context_settings

            allocator = TokenBudgetAllocator(load_context_settings())
            est_tokens = allocator.estimate_messages_tokens(history)
            threshold = available_tokens or load_context_settings().compact_threshold_tokens
            token_budget_meta = {
                "estimated_tokens": est_tokens,
                "compact_threshold_tokens": threshold,
            }
            if est_tokens <= threshold and before_count <= self.MAX_MESSAGES:
                return CompactionResult(
                    messages=list(history),
                    stats=ContextStats(
                        history_messages_before=before_count, history_messages_after=before_count,
                        history_chars_before=before_chars, history_chars_after=before_chars,
                        compacted=False, summary_chars=0,
                        verbatim_tokens_before=est_tokens, verbatim_tokens_after=est_tokens,
                    ),
                    truncated=False,
                )
        except Exception:
            est_tokens = before_chars // _CHARS_PER_TOKEN
            token_budget_meta = {"estimated_tokens": est_tokens}
            if before_count <= self.MAX_MESSAGES:
                return CompactionResult(
                    messages=list(history),
                    stats=ContextStats(
                        history_messages_before=before_count, history_messages_after=before_count,
                        history_chars_before=before_chars, history_chars_after=before_chars,
                        compacted=False, summary_chars=0,
                    ),
                    truncated=False,
                )

        # Não cabe — compactar
        recent = history[-self.KEEP_RECENT:] if self.KEEP_RECENT > 0 else []
        older = history[: max(0, len(history) - len(recent))]

        if not older:
            truncated_history = history[-self.MAX_MESSAGES:]
            after_count = len(truncated_history)
            after_chars = sum(len(m.get("content", "")) for m in truncated_history)
            return CompactionResult(
                messages=truncated_history,
                stats=ContextStats(
                    history_messages_before=before_count, history_messages_after=after_count,
                    history_chars_before=before_chars, history_chars_after=after_chars,
                    compacted=True, summary_chars=0, compaction_mode="truncate",
                ),
                truncated=True,
            )

        # Summarization progressiva
        summary_text, summary_version = self._progressive_summarize(older, session_id, tenant_id)

        result_messages: list[dict[str, str]] = []
        if summary_text:
            result_messages.append({"role": "system", "content": f"[SUMMARY v{summary_version}]\n{summary_text}"})
        result_messages.extend(recent)

        after_count = len(result_messages)
        after_chars = sum(len(m.get("content", "")) for m in result_messages)

        return CompactionResult(
            messages=result_messages,
            stats=ContextStats(
                history_messages_before=before_count, history_messages_after=after_count,
                history_chars_before=before_chars, history_chars_after=after_chars,
                compacted=True, summary_chars=len(summary_text or ""),
                summary_provenance="context_pipeline", summary_version=summary_version,
                compaction_mode="progressive_summarize",
            ),
            truncated=True, summary_applied=summary_text, summary_version=summary_version,
        )

    def _progressive_summarize(
        self, older: list[dict[str, str]], session_id: str | None, tenant_id: str,
    ) -> tuple[str | None, int | None]:
        prev_summary, prev_version = self._load_summary(session_id, tenant_id)
        text = self._msgs_to_text(older)
        if prev_summary:
            text = f"[Resumo anterior v{prev_version}]\n{prev_summary}\n\n[Novas mensagens]\n{text}"

        try:
            from app.clients import call_llm

            summary = call_llm(
                f"Resume esta conversa em português (máx 300 palavras). "
                f"Foca nos factos, decisões técnicas, ficheiros modificados.\n\n{text}",
                history=[], profile="balanced", model_override=None, allowlist_mode="modality",
            )
            summary = summary.strip()[: self.SUMMARY_MAX_CHARS]
        except Exception:
            logger.debug("Summarization failed", exc_info=True)
            return prev_summary, prev_version

        if not summary:
            return prev_summary, prev_version

        new_version = (prev_version or 0) + 1
        self._save_summary(session_id, tenant_id, new_version, summary)
        return summary, new_version

    def _load_summary(self, session_id: str | None, tenant_id: str) -> tuple[str | None, int | None]:
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
            logger.debug("Failed to load summary", exc_info=True)
        return None, None

    def _save_summary(self, session_id: str | None, tenant_id: str, version: int, text: str) -> None:
        if not session_id:
            return
        try:
            from app.shared.pg_tenant import connect_pg

            with connect_pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO session_summaries (tenant_id, session_id, version, summary_text, provenance) "
                    "VALUES (%s, %s, %s, %s, 'context_pipeline') "
                    "ON CONFLICT (tenant_id, session_id, version) DO UPDATE "
                    "SET summary_text = EXCLUDED.summary_text, provenance = EXCLUDED.provenance",
                    (tenant_id, session_id, version, text),
                )
        except Exception:
            logger.debug("Failed to save summary", exc_info=True)

    @staticmethod
    def _msgs_to_text(messages: list[dict[str, str]]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "unknown")
            content = str(m.get("content", ""))[:500]
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines)


# Feature flag: ContextEngine is the default since Onda 3.
# Set CONTEXT_ENGINE_DISABLED=1 to fall back to the classic monolithic pipeline
# (for emergency rollback only — will be removed in a future release).
# Default: on (uses the pluggable ContextEngine).

def _use_new_engine() -> bool:
    """Check if ContextEngine should be used (default: ON)."""
    try:
        from app.config import CONTEXT_ENGINE_DISABLED
        if bool(CONTEXT_ENGINE_DISABLED):
            import logging
            logging.getLogger(__name__).warning(
                "CONTEXT_ENGINE_DISABLED=1 — using classic pipeline (deprecated). "
                "This fallback will be removed in a future release."
            )
            return False
        return True
    except Exception:
        return True  # Engine is the default


# ═══════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════

class ContextPipeline:
    """Pipeline único de montagem de contexto."""

    def __init__(self) -> None:
        self._layer_cache: dict[str, SystemLayers] = {}
        self._tools = ToolInjector()
        self._window = ContextWindowManager()

    def assemble(
        self, payload: Any, request_id: str, *,
        agent_name: str | None = None,
        connector_alive: bool = False,
        mode: str = "web",
        workspace_path: str | None = None,
        connector_id: str | None = None,
        tenant_id: str = "default",
    ) -> AssembledContext:
        # Feature flag: delegate to pluggable ContextEngine
        if _use_new_engine():
            return self._assemble_via_engine(
                payload, request_id,
                agent_name=agent_name,
                connector_alive=connector_alive,
                mode=mode,
                workspace_path=workspace_path,
                connector_id=connector_id,
                tenant_id=tenant_id,
            )

        t0 = time.monotonic()
        user_text = getattr(payload, "text", "")
        history = self._normalize_history(payload)

        # ── System layers L1–L4 ──
        layers = self._compose_system_layers(
            agent_name=agent_name,
            connector_alive=connector_alive,
            mode=mode,
            workspace_path=workspace_path,
            connector_id=connector_id,
            tenant_id=tenant_id,
        )

        # ── Tools ──
        openai_tools, catalog_names = self._tools.select_and_inject(
            str(user_text), history, layers.messages,
            connector_alive=connector_alive,
        )

        # ── L5: session history compact ──
        session_id = getattr(payload, "chat_session_id", None) or ""
        result = self._window.compact(
            history,
            session_id=session_id if session_id else None,
            tenant_id=tenant_id,
            request_id=str(getattr(payload, "request_id", "") or request_id),
        )
        compacted, ctx_stats, truncated = result.messages, result.stats, result.truncated
        token_accounting = {
            "verbatim_tokens_before": getattr(ctx_stats, "verbatim_tokens_before", None),
            "verbatim_tokens_after": getattr(ctx_stats, "verbatim_tokens_after", None),
            "compacted": bool(getattr(ctx_stats, "compacted", truncated)),
            "compaction_mode": getattr(ctx_stats, "compaction_mode", None),
        }

        layers_applied = list(layers.layers_applied)
        layers_applied.append("L5")

        # ── Build ──
        injected: list[dict[str, str]] = []
        injected.extend(layers.messages)
        injected.append({"role": "system", "content": f"[TOOLS] {', '.join(catalog_names)}"})
        injected.extend(compacted)
        injected.append({"role": "user", "content": str(user_text)})

        build_ms = (time.monotonic() - t0) * 1000
        layer_label = "+".join(layers_applied) if layers_applied else "none"
        logger.info(
            "context_pipeline assemble request_id=%s layers=%s build_ms=%.1f tools=%d mode=%s",
            request_id, layer_label, build_ms, len(openai_tools), mode,
        )
        return AssembledContext(
            injected_history=injected, ctx_stats=ctx_stats, session_truncated=truncated,
            recall_count=int(layers.layer_meta.get("L4", {}).get("rule_count") or 0),
            injection_meta={
                "pipeline": "context_pipeline",
                "build_ms": round(build_ms, 2),
                "layers": layers_applied,
                "layer_meta": layers.layer_meta,
                "agent_name": layers.agent_name,
                "skill_names": layers.skill_names,
                "connector_alive": connector_alive,
                "mode": mode,
                "workspace_path": workspace_path,
                "tenant_id": tenant_id,
                "tools_injected": len(openai_tools),
                "tools_active": self._tools.get_active_count(),
                "tools_catalog": catalog_names,
                "token_accounting": token_accounting,
            },
            openai_tools=openai_tools,
        )

    def _normalize_history(self, payload: Any) -> list[dict[str, str]]:
        raw = getattr(payload, "history", None) or []
        return [
            {"role": str(getattr(m, "role", "")), "content": str(getattr(m, "content", ""))}
            for m in raw
            if str(getattr(m, "role", "")) in ("user", "assistant", "system")
        ]

    def _compose_system_layers(
        self, *,
        agent_name: str | None,
        connector_alive: bool,
        mode: str,
        workspace_path: str | None = None,
        connector_id: str | None = None,
        tenant_id: str = "default",
    ) -> SystemLayers:
        cache_key = f"{agent_name or '__default__'}:{workspace_path or ''}:{tenant_id}:{mode}"
        if cache_key in self._layer_cache:
            return self._layer_cache[cache_key]

        t0 = time.monotonic()
        messages: list[dict[str, str]] = []
        skill_names: list[str] = []
        layers_applied: list[str] = []
        layer_meta: dict[str, Any] = {}

        # L1 — system anchor (bundled prompt + product pack)
        l1_msgs, l1_audit = self._layer_l1_system_anchor()
        if l1_msgs:
            messages.extend(l1_msgs)
            layers_applied.append("L1")
            layer_meta["L1"] = l1_audit

        # L2 — workspace + git metadata
        l2_msg, l2_meta = self._layer_l2_workspace(workspace_path, connector_id=connector_id)
        if l2_msg:
            messages.append(l2_msg)
            layers_applied.append("L2")
            layer_meta["L2"] = l2_meta

        # L3 — team agent + skills (tenant catalog; fallback user_*)
        l3_msgs, agent_resolved, skills_used = self._layer_l3_agent_skills(agent_name, tenant_id)
        messages.extend(l3_msgs)
        skill_names = skills_used
        if l3_msgs:
            layers_applied.append("L3")
            layer_meta["L3"] = {"agent_name": agent_resolved, "skill_names": skills_used}

        # L4 — approved team rules (pgvector table; no-op if missing)
        l4_msg, l4_meta = self._layer_l4_team_rules(tenant_id)
        if l4_msg:
            messages.append(l4_msg)
            layers_applied.append("L4")
            layer_meta["L4"] = l4_meta

        messages.append({"role": "system", "content": self._env_block(connector_alive, mode)})

        layers = SystemLayers(
            messages=messages,
            agent_name=agent_resolved or "default",
            skill_names=skill_names,
            build_ms=(time.monotonic() - t0) * 1000,
            layers_applied=layers_applied,
            layer_meta=layer_meta,
        )
        self._layer_cache[cache_key] = layers
        return layers

    @staticmethod
    def _layer_l1_system_anchor() -> tuple[list[dict[str, str]], dict[str, Any]]:
        try:
            from app.config import CENTRAL_FOCUS_MODE, CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED
            from app.shared.system_prompt_loader import build_system_prompt_injection_messages

            if not CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED or CENTRAL_FOCUS_MODE:
                return [], {"skipped": True}
            msgs, audit = build_system_prompt_injection_messages()
            return list(msgs), audit
        except Exception:
            logger.debug("L1 system anchor failed", exc_info=True)
            return [], {"skipped": True, "error": "load_failed"}

    @staticmethod
    def _layer_l2_workspace(workspace_path: str | None, *, connector_id: str | None = None) -> tuple[dict[str, str] | None, dict[str, Any]]:
        # Phase 3: connector-provided context takes priority
        if connector_id:
            from app.http.router_connector import get_connector_context
            ctx = get_connector_context(connector_id)
            if ctx:
                parts = [f"[WORKSPACE L2 via connector {connector_id}]"]
                if ctx.get("git_branch"):
                    parts.append(f"Branch: {ctx['git_branch']}{' (dirty)' if ctx.get('git_dirty') else ''}")
                if ctx.get("active_file"):
                    parts.append(f"Active file: {ctx['active_file']}")
                if ctx.get("repo_structure"):
                    parts.append(f"Repo structure:\n{ctx['repo_structure']}")
                if ctx.get("recent_changes"):
                    parts.append(f"Recent changes:\n{ctx['recent_changes']}")
                body = "\n".join(parts)
                return {"role": "system", "content": body}, {"connector_id": connector_id, "source": "connector", **ctx}
        # Fallback: local filesystem
        if not workspace_path:
            return None, {}
        try:
            from app.shared.repo_context import collect_git_metadata, format_repo_context_block

            git_meta = collect_git_metadata(workspace_path)
            body = format_repo_context_block(workspace_path=workspace_path, git_meta=git_meta)
            meta = {"workspace_path": workspace_path, **git_meta}
            return {"role": "system", "content": body}, meta
        except Exception:
            logger.debug("L2 workspace layer failed for %s", workspace_path, exc_info=True)
            body = f"[WORKSPACE L2]\npath={workspace_path}"
            return {"role": "system", "content": body}, {"workspace_path": workspace_path}

    def _layer_l3_agent_skills(
        self, agent_name: str | None, tenant_id: str,
    ) -> tuple[list[dict[str, str]], str, list[str]]:
        messages: list[dict[str, str]] = []
        resolved = (agent_name or "").strip() or "default"
        agent_prompt = self._load_agent_prompt(resolved, tenant_id)
        if agent_prompt:
            messages.append({"role": "system", "content": agent_prompt})
        skills_msgs, skills_used = self._load_skills(tenant_id)
        messages.extend(skills_msgs)
        return messages, resolved, skills_used

    @staticmethod
    def _layer_l4_team_rules(tenant_id: str) -> tuple[dict[str, str] | None, dict[str, Any]]:
        try:
            from app.memory_service import recall_approved_rule_patterns

            patterns = recall_approved_rule_patterns(tenant_id=tenant_id, limit=8)
            if not patterns:
                return None, {"rule_count": 0}
            body = "[TEAM_RULES L4]\n" + "\n".join(f"- {p}" for p in patterns)
            return {"role": "system", "content": body}, {"rule_count": len(patterns)}
        except Exception:
            logger.debug("L4 team_rules unavailable", exc_info=True)
            return None, {"rule_count": 0, "skipped": True}

    def _load_agent_prompt(self, agent_name: str, tenant_id: str) -> str:
        try:
            from app.memory_service import list_team_agents

            for row in list_team_agents(tenant_id=tenant_id):
                if str(row.get("name") or "") == agent_name:
                    prompt = str(row.get("prompt") or "").strip()
                    if prompt:
                        return prompt
        except Exception:
            logger.debug("team_agents load failed for %s", agent_name, exc_info=True)
        return self._load_agent_prompt_user(agent_name)

    @staticmethod
    def _load_agent_prompt_user(agent_name: str) -> str:
        try:
            from app.user_config import _user_id
            from app.shared.pg_tenant import connect_pg

            uid = _user_id()
            with connect_pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT prompt FROM user_agents WHERE user_id=%s AND name=%s LIMIT 1",
                    (uid, agent_name),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
        except Exception:
            logger.debug("user_agents fallback failed for %s", agent_name, exc_info=True)
        return ""

    def _load_skills(self, tenant_id: str) -> tuple[list[dict[str, str]], list[str]]:
        try:
            from app.memory_service import list_team_skills

            rows = list_team_skills(tenant_id=tenant_id)
            if rows:
                msgs, names = [], []
                for row in rows:
                    name = str(row.get("name") or "")
                    prompt = str(row.get("prompt") or "").strip()
                    if prompt:
                        msgs.append({"role": "system", "content": f"[SKILL: {name}]\n{prompt}"})
                        names.append(name)
                if msgs:
                    return msgs, names
        except Exception:
            logger.debug("team_skills load failed", exc_info=True)
        return self._load_skills_user()

    @staticmethod
    def _load_skills_user() -> tuple[list[dict[str, str]], list[str]]:
        try:
            from app.user_config import _user_id
            from app.shared.pg_tenant import connect_pg

            uid = _user_id()
            with connect_pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT name, prompt FROM user_skills WHERE user_id=%s AND enabled=true ORDER BY name",
                    (uid,),
                )
                rows = cur.fetchall()
            msgs, names = [], []
            for r in rows:
                name, prompt = str(r[0]), str(r[1] or "").strip()
                if prompt:
                    msgs.append({"role": "system", "content": f"[SKILL: {name}]\n{prompt}"})
                    names.append(name)
            return msgs, names
        except Exception:
            logger.debug("user_skills fallback failed", exc_info=True)
            return [], []

    @staticmethod
    def _assemble_via_engine(
        payload: Any, request_id: str, *,
        agent_name: str | None = None,
        connector_alive: bool = False,
        mode: str = "web",
        workspace_path: str | None = None,
        connector_id: str | None = None,
        tenant_id: str = "default",
    ) -> AssembledContext:
        """Delegate assembly to the pluggable ContextEngine."""
        from app.context_engine import assemble_context_sync

        user_text = str(getattr(payload, "text", ""))
        history = ContextPipeline._normalize_history_static(payload)
        session_id = getattr(payload, "chat_session_id", None) or None

        state = assemble_context_sync(
            request_id=request_id,
            user_text=user_text,
            history=history,
            tenant_id=tenant_id,
            session_id=session_id,
            agent_name=agent_name,
            mode=mode,
            connector_alive=connector_alive,
            connector_id=connector_id,
            workspace_path=workspace_path,
        )

        return AssembledContext(
            injected_history=state.messages,
            ctx_stats=ContextStats(
                history_messages_before=len(history),
                history_messages_after=len(state.messages),
                history_chars_before=sum(len(m.get("content", "")) for m in history),
                history_chars_after=sum(len(m.get("content", "")) for m in state.messages),
                compacted=state.session_truncated,
                summary_chars=0,
            ),
            session_truncated=state.session_truncated,
            recall_count=state.recall_count,
            injection_meta={
                "pipeline": "context_engine",
                "build_ms": state.build_ms,
                "layers": state.layers_applied,
                "layer_meta": state.meta,
                "agent_name": state.meta.get("agent_name", "default"),
                "skill_names": state.meta.get("skill_names", []),
                "connector_alive": connector_alive,
                "mode": mode,
                "workspace_path": workspace_path,
                "tenant_id": tenant_id,
                "tools_injected": len(state.tools),
                "tools_active": len(state.tools),
                "tools_catalog": state.tool_catalog,
                "token_accounting": state.meta.get("token_accounting", {}),
                "engine": "context_engine",
            },
            openai_tools=state.tools,
        )

    @staticmethod
    def _normalize_history_static(payload: Any) -> list[dict[str, str]]:
        raw = getattr(payload, "history", None) or []
        return [
            {"role": str(getattr(m, "role", "")), "content": str(getattr(m, "content", ""))}
            for m in raw
            if str(getattr(m, "role", "")) in ("user", "assistant", "system")
        ]

    @staticmethod
    def _env_block(connector_alive: bool, mode: str) -> str:
        if mode == "cli":
            return "[ENV] CentralChat CLI."
        if connector_alive:
            return "[ENV] CentralChat Web + Connector ativo.\n      Workspace exposto no teu PC."
        return (
            "[ENV] CentralChat Web — chat.\n"
            "      Sem acesso a ficheiros.\n"
            "      Para ler, editar e executar no teu ambiente,\n"
            "      instala o Central Connector no teu PC."
        )
