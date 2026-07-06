"""System layers step — L1 (system anchor), L2 (workspace), L3 (agent+skills), L4 (team rules), [ENV].

Extracted from context_pipeline.py:_compose_system_layers().
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.context_engine.registry import ContextStep, Phase, register_step
from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)

# Simple in-memory cache for system layers (same params → same output)
_layer_cache: dict[str, tuple[list[dict[str, str]], list[str], dict[str, Any]]] = {}


@register_step
class SystemLayersStep:
    """Builds L1–L4 system messages + [ENV] block.

    Phase: gather (runs before RAG and tool selection).
    Priority: 10 (first gather step).
    """

    name = "gather.system_layers"
    phase = Phase.GATHER
    priority = 10

    async def should_run(self, state: ContextState) -> bool:
        return True  # Always runs — provides the system foundation

    async def run(self, state: ContextState) -> ContextState:
        cache_key = f"{state.agent_name or '__default__'}:{state.workspace_path or ''}:{state.tenant_id}:{state.mode}"
        if cache_key in _layer_cache:
            msgs, layers, meta = _layer_cache[cache_key]
            # Prepend system messages and extend layers (preserve RESOLVE phase additions)
            state.messages = msgs + state.messages
            for layer in layers:
                if layer not in state.layers_applied:
                    state.layers_applied.append(layer)
            state.meta.update(meta)
            return state

        t0 = time.monotonic()
        messages: list[dict[str, str]] = []
        layers_applied: list[str] = []
        layer_meta: dict[str, Any] = {}

        # L1 — system anchor
        l1_msgs, l1_audit = _build_l1()
        if l1_msgs:
            messages.extend(l1_msgs)
            layers_applied.append("L1")
            layer_meta["L1"] = l1_audit

        # L2 — workspace
        l2_msg, l2_meta = _build_l2(state.workspace_path, connector_id=state.connector_id)
        if l2_msg:
            messages.append(l2_msg)
            layers_applied.append("L2")
            layer_meta["L2"] = l2_meta

        # L3 — agent + skills
        l3_msgs, agent_resolved, skills_used = await _build_l3(
            state.agent_name, state.tenant_id, state.user_id,
        )
        messages.extend(l3_msgs)
        if l3_msgs:
            layers_applied.append("L3")
            layer_meta["L3"] = {"agent_name": agent_resolved, "skill_names": skills_used}
            state.meta["agent_name"] = agent_resolved
            state.meta["skill_names"] = skills_used
        else:
            state.meta["agent_name"] = "default"
            state.meta["skill_names"] = []

        # L4 — team rules
        l4_msg, l4_meta = _build_l4(state.tenant_id)
        if l4_msg:
            messages.append(l4_msg)
            layers_applied.append("L4")
            layer_meta["L4"] = l4_meta

        # [ENV] block
        messages.append({"role": "system", "content": _env_block(state.connector_alive, state.mode)})

        # Cache
        _layer_cache[cache_key] = (messages, layers_applied, layer_meta)

        # Prepend system messages (keep any messages from RESOLVE phase)
        state.messages = messages + state.messages
        # Extend layers_applied (keep any layers added by RESOLVE phase)
        for layer in layers_applied:
            if layer not in state.layers_applied:
                state.layers_applied.append(layer)
        state.meta.update(layer_meta)
        state.meta["layer_build_ms"] = round((time.monotonic() - t0) * 1000, 2)

        return state


# ═══════════════════════════════════════════════════════════════
# Layer builders (extracted from context_pipeline.py)
# ═══════════════════════════════════════════════════════════════

def _build_l1() -> tuple[list[dict[str, str]], dict[str, Any]]:
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


def _build_l2(
    workspace_path: str | None,
    *,
    connector_id: str | None = None,
) -> tuple[dict[str, str] | None, dict[str, Any]]:
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


async def _build_l3(
    agent_name: str | None,
    tenant_id: str,
    user_id: str,
) -> tuple[list[dict[str, str]], str, list[str]]:
    messages: list[dict[str, str]] = []
    resolved = (agent_name or "").strip() or "default"
    agent_prompt = _load_agent_prompt(resolved, tenant_id, user_id)
    if agent_prompt:
        messages.append({"role": "system", "content": agent_prompt})
    skills_msgs, skills_used = _load_skills(tenant_id, user_id)
    messages.extend(skills_msgs)
    return messages, resolved, skills_used


def _load_agent_prompt(agent_name: str, tenant_id: str, user_id: str) -> str:
    try:
        from app.memory_service import list_team_agents
        for row in list_team_agents(tenant_id=tenant_id):
            if str(row.get("name") or "") == agent_name:
                prompt = str(row.get("prompt") or "").strip()
                if prompt:
                    return prompt
    except Exception:
        logger.debug("team_agents load failed for %s", agent_name, exc_info=True)
    return _load_agent_prompt_user(agent_name, user_id)


def _load_agent_prompt_user(agent_name: str, user_id: str) -> str:
    try:
        from app.shared.pg_tenant import connect_pg
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT prompt FROM user_agents WHERE user_id=%s AND name=%s LIMIT 1",
                (user_id, agent_name),
            )
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0]).strip()
    except Exception:
        logger.debug("user_agents fallback failed for %s", agent_name, exc_info=True)
    return ""


def _load_skills(tenant_id: str, user_id: str) -> tuple[list[dict[str, str]], list[str]]:
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
    return _load_skills_user(user_id)


def _load_skills_user(user_id: str) -> tuple[list[dict[str, str]], list[str]]:
    try:
        from app.shared.pg_tenant import connect_pg
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT name, prompt FROM user_skills WHERE user_id=%s AND enabled=true ORDER BY name",
                (user_id,),
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


def _build_l4(tenant_id: str) -> tuple[dict[str, str] | None, dict[str, Any]]:
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
