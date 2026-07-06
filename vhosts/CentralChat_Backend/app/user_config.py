"""M2 — User-scoped configuration: cloud models, agents, skills, preferences.

Per-user REST endpoints with optimistic concurrency (version field).
Scoped by user_id extracted from JWT sub claim.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.config import CLOUD_ROUTER_PROFILE
from app.inference import get_vendor_catalog_cached
from app.shared.inference_governance import (
    KNOWN_PROVIDERS,
    effective_catalog_ids,
    filter_vendor_catalog,
    governance_summary,
    list_providers_public,
    merge_user_cloud_models,
    validate_user_cloud_models_payload,
)
from app.shared.pg_tenant import connect_pg, resolve_pg_tenant_id
from app.shared.tenant_context import get_current_sub

logger = logging.getLogger(__name__)

router_user_config = APIRouter()

# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════


def _user_id() -> str:
    """Resolve user UUID from JWT sub claim. Raises 401 if missing."""
    sub = get_current_sub()
    if not sub:
        raise HTTPException(401, "unauthenticated")
    return sub


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_provider(model_id: str) -> str:
    """Extrai o provider real de um model_id.

    openrouter/anthropic/claude-sonnet → anthropic (se conhecido)
    openai/gpt-4o                    → openai
    openrouter/unknown/model         → openrouter (fallback)
    """
    parts = model_id.split("/")
    if len(parts) >= 3 and parts[0] == "openrouter":
        candidate = parts[1]
        if candidate in KNOWN_PROVIDERS and candidate != "openrouter":
            return candidate
    if len(parts) >= 2 and parts[0] in KNOWN_PROVIDERS and parts[0] != "openrouter":
        return parts[0]
    return "openrouter"


# ═══════════════════════════════════════════
# 1. CLOUD MODELS
# ═══════════════════════════════════════════


_OPENROUTER_MODELS_CACHE: dict[str, Any] = {}
_OPENROUTER_MODELS_CACHE_TTL = 300.0  # 5 minutos


def _fetch_openrouter_models_direct() -> list[dict[str, str]] | None:
    """Busca lista de modelos directo da API OpenRouter (fallback sem model-router)."""
    import time as _time

    from app.config import OPENROUTER_API_KEY

    key = (OPENROUTER_API_KEY or "").strip()
    if not key:
        return None

    # Cache in-process
    now = _time.monotonic()
    cached = _OPENROUTER_MODELS_CACHE
    if cached and (now - cached.get("fetched_at", 0)) < _OPENROUTER_MODELS_CACHE_TTL:
        return cached.get("rows")

    try:
        import httpx

        r = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://central.nousresearch.com",
                "X-Title": "Central",
            },
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        raw = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return None

        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            name = str(item.get("name") or mid).strip()
            ctx = item.get("context_length")
            row: dict[str, str] = {"id": mid, "label": name}
            if isinstance(ctx, (int, float)) and ctx > 0:
                row["context_length"] = str(int(ctx))
            rows.append(row)

        _OPENROUTER_MODELS_CACHE["rows"] = rows
        _OPENROUTER_MODELS_CACHE["fetched_at"] = now
        return rows
    except Exception:
        logger.debug("_fetch_openrouter_models_direct: failed", exc_info=True)
        return None


@router_user_config.get("/ui/cloud-models", tags=["WidgetMVP"])
def user_cloud_models_get() -> dict[str, Any]:
    """Lista de modelos do user + merge com catálogo do fornecedor (OpenRouter).

    Devolve todos os modelos disponíveis no fornecedor, com os flags
    enabled/disabled do user. Modelos que o user nunca configurou
    aparecem como enabled por defeito.
    """
    uid = _user_id()

    # ── 1. Carrega os modelos do user (tabela per-user) ──
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT model_id, label, enabled, version, source, updated_at "
            "FROM user_cloud_models WHERE user_id=%s ORDER BY model_id",
            (uid,),
        )
        rows = cur.fetchall()
        # Mapa: model_id → { enabled, label }
        user_map: dict[str, dict[str, Any]] = {}
        for r in rows:
            user_map[r[0]] = {"label": r[1], "enabled": r[2]}

        cur.execute("SELECT COALESCE(MAX(version), 0) FROM user_cloud_models WHERE user_id=%s", (uid,))
        version = cur.fetchone()[0]

    # ── 2. Busca o catálogo do fornecedor ──
    # Primário: busca directa da API OpenRouter (OPENROUTER_API_KEY).
    # Fallback legado: model-router (MODEL_ROUTER_URL) para compatibilidade.
    vendor_rows_raw = _fetch_openrouter_models_direct()
    if vendor_rows_raw is None:
        try:
            vendor_rows_raw, _vendor_err = get_vendor_catalog_cached(CLOUD_ROUTER_PROFILE, refresh=False)
        except Exception:
            logger.debug("user_cloud_models_get: vendor catalog fetch failed", exc_info=True)

    vendor_rows: list[dict[str, str]] = vendor_rows_raw if vendor_rows_raw else []

    tid = resolve_pg_tenant_id()
    vendor_rows = filter_vendor_catalog(vendor_rows, tenant_id=tid)
    allowed_ids = effective_catalog_ids(vendor_rows, tenant_id=tid)

    # ── 3. Merge: vendor catalog + user enabled/disabled flags ──
    models = merge_user_cloud_models(vendor_rows, user_map)

    # ── 4. Resolve real provider for each model ──
    for m in models:
        m["provider"] = _resolve_provider(m["id"])

    # ── 5. Build providers summary with model counts ──
    providers = list_providers_public()
    model_counts: dict[str, int] = {}
    for m in models:
        p = m.get("provider", "openrouter")
        model_counts[p] = model_counts.get(p, 0) + 1
    for p in providers:
        pid = p["id"]
        p["model_count"] = model_counts.get(pid, 0)
        if not p["configured"] and pid != "openrouter":
            meta = KNOWN_PROVIDERS.get(pid, {})
            env_key = meta.get("env_key", "")
            p["setup_hint"] = f"Defina {env_key} no .env" if env_key else "Configure a API key no admin"

    gov = governance_summary(tenant_id=tid)
    return {
        "models": models,
        "providers": providers,
        "version": int(version),
        "governance": {
            "providers_configured": gov["providers_configured"],
            "providers_total": gov["providers_total"],
            "catalog_count": len(models),
            "tenant_restricted": gov["tenant_allowlist_restricted"],
            "global_restricted": gov["global_allowlist_restricted"],
        },
    }


@router_user_config.put("/ui/cloud-models", tags=["WidgetMVP"])
def user_cloud_models_put(payload: dict[str, Any]) -> dict[str, Any]:
    """Substitui lista de modelos do user. Body: { models: [...], version: N }.

    Retorna 409 se a version não bater (outro cliente escreveu primeiro).
    """
    uid = _user_id()
    models = payload.get("models", [])
    client_version = payload.get("version", 0)
    source = payload.get("source", "web")

    if not isinstance(models, list) or not all(isinstance(m, dict) and "id" in m for m in models):
        raise HTTPException(422, "models must be a list of {id, label, enabled}")

    tid = resolve_pg_tenant_id()
    vendor_rows_raw = _fetch_openrouter_models_direct()
    if vendor_rows_raw is None:
        try:
            vendor_rows_raw, _vendor_err = get_vendor_catalog_cached(CLOUD_ROUTER_PROFILE, refresh=False)
        except Exception:
            vendor_rows_raw = []
    vendor_rows = filter_vendor_catalog(vendor_rows_raw or [], tenant_id=tid)
    allowed_ids = effective_catalog_ids(vendor_rows, tenant_id=tid)
    try:
        validate_user_cloud_models_payload(models, allowed_ids)
    except ValueError as exc:
        code = str(exc)
        status = 403 if "tenant" in code or "policy" in code else 400
        raise HTTPException(status_code=status, detail=code) from exc

    now = _now()
    with connect_pg() as conn, conn.cursor() as cur:
        # Check version
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM user_cloud_models WHERE user_id=%s", (uid,))
        server_version = cur.fetchone()[0]

        if client_version != server_version:
            # Re-read current state to return in conflict response
            cur.execute(
                "SELECT model_id, label, enabled FROM user_cloud_models WHERE user_id=%s ORDER BY model_id",
                (uid,),
            )
            current = [
                {"id": r[0], "label": r[1], "enabled": r[2]} for r in cur.fetchall()
            ]
            return {
                "error": "version_mismatch",
                "current_version": server_version,
                "your_version": client_version,
                "last_modified_by": "unknown",  # Could query source from a row
                "current_state": {"models": current},
            }

        # Atomic replace: delete all, insert new
        cur.execute("DELETE FROM user_cloud_models WHERE user_id=%s", (uid,))
        new_version = server_version + 1
        for m in models:
            cur.execute(
                "INSERT INTO user_cloud_models (user_id, model_id, label, enabled, version, source, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (uid, m["id"], m.get("label", ""), m.get("enabled", True), new_version, source, now),
            )

    return {"ok": True, "version": new_version}


# ═══════════════════════════════════════════
# 2. AGENTS
# ═══════════════════════════════════════════


@router_user_config.get("/ui/agents", tags=["WidgetMVP"])
def user_agents_get() -> dict[str, Any]:
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, prompt, model_id, icon, version, source, created_at, updated_at "
            "FROM user_agents WHERE user_id=%s ORDER BY name",
            (uid,),
        )
        agents = [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "prompt": str(r[2]),
                "model_id": str(r[3]) if r[3] else None,
                "icon": str(r[4]) if r[4] else "",
                "version": int(r[5]),
                "source": str(r[6]),
                "created_at": str(r[7]),
                "updated_at": str(r[8]),
            }
            for r in cur.fetchall()
        ]
    return {"agents": agents}


@router_user_config.post("/ui/agents", tags=["WidgetMVP"])
def user_agents_create(payload: dict[str, Any]) -> dict[str, Any]:
    uid = _user_id()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(422, "name is required")
    prompt = str(payload.get("prompt", ""))
    model_id = payload.get("model_id")
    icon = str(payload.get("icon", "")).strip()
    now = _now()

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_agents (user_id, name, prompt, model_id, icon, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (uid, name, prompt, model_id, icon, now),
        )
        agent_id = str(cur.fetchone()[0])
    return {
        "agent": {
            "id": agent_id,
            "name": name,
            "prompt": prompt,
            "model_id": model_id,
            "icon": icon,
            "version": 1,
            "source": "web",
            "created_at": now,
            "updated_at": now,
        }
    }


@router_user_config.patch("/ui/agents/{agent_id}", tags=["WidgetMVP"])
def user_agents_update(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    uid = _user_id()
    client_version = payload.get("version", 0)
    fields = []

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT version, name, prompt, model_id, icon FROM user_agents WHERE id=%s AND user_id=%s",
            (agent_id, uid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "agent_not_found")

        server_version = int(row[0])
        if client_version != server_version:
            return {
                "error": "version_mismatch",
                "current_version": server_version,
                "your_version": client_version,
                "agent_id": agent_id,
            }

        if "name" in payload:
            fields.append(("name", str(payload["name"]).strip()))
        if "prompt" in payload:
            fields.append(("prompt", str(payload["prompt"])))
        if "model_id" in payload:
            fields.append(("model_id", payload["model_id"]))
        if "icon" in payload:
            fields.append(("icon", str(payload.get("icon", "")).strip()))

        if fields:
            new_version = server_version + 1
            now = _now()
            set_clauses = ", ".join(f"{col}=%s" for col, _ in fields)
            vals = [v for _, v in fields] + [new_version, now, agent_id, uid]
            cur.execute(
                f"UPDATE user_agents SET {set_clauses}, version=%s, updated_at=%s "
                f"WHERE id=%s AND user_id=%s",
                vals,
            )
    return {"ok": True, "agent_id": agent_id}


@router_user_config.delete("/ui/agents/{agent_id}", tags=["WidgetMVP"])
def user_agents_delete(agent_id: str) -> dict[str, Any]:
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM user_agents WHERE id=%s AND user_id=%s", (agent_id, uid))
        if cur.rowcount == 0:
            raise HTTPException(404, "agent_not_found")
    return {"ok": True}


# ═══════════════════════════════════════════
# 3. SKILLS
# ═══════════════════════════════════════════


@router_user_config.get("/ui/skills", tags=["WidgetMVP"])
def user_skills_get() -> dict[str, Any]:
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, description, prompt, enabled, version, source, created_at, updated_at "
            "FROM user_skills WHERE user_id=%s ORDER BY name",
            (uid,),
        )
        skills = [
            {
                "id": str(r[0]),
                "name": str(r[1]),
                "description": str(r[2]),
                "prompt": str(r[3]),
                "enabled": bool(r[4]),
                "version": int(r[5]),
                "source": str(r[6]),
                "created_at": str(r[7]),
                "updated_at": str(r[8]),
            }
            for r in cur.fetchall()
        ]
    return {"skills": skills}


@router_user_config.post("/ui/skills", tags=["WidgetMVP"])
def user_skills_create(payload: dict[str, Any]) -> dict[str, Any]:
    uid = _user_id()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(422, "name is required")
    description = str(payload.get("description", ""))
    prompt = str(payload.get("prompt", ""))
    now = _now()

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_skills (user_id, name, description, prompt, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (uid, name, description, prompt, now),
        )
        skill_id = str(cur.fetchone()[0])
    return {
        "skill": {
            "id": skill_id,
            "name": name,
            "description": description,
            "prompt": prompt,
            "enabled": True,
            "version": 1,
            "source": "web",
            "created_at": now,
            "updated_at": now,
        }
    }


@router_user_config.patch("/ui/skills/{skill_id}", tags=["WidgetMVP"])
def user_skills_update(skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    uid = _user_id()
    client_version = payload.get("version", 0)
    fields = []

    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT version FROM user_skills WHERE id=%s AND user_id=%s",
            (skill_id, uid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "skill_not_found")

        server_version = int(row[0])
        if client_version != server_version:
            return {
                "error": "version_mismatch",
                "current_version": server_version,
                "your_version": client_version,
                "skill_id": skill_id,
            }

        for key in ("name", "description", "prompt"):
            if key in payload:
                fields.append((key, str(payload[key])))
        if "enabled" in payload:
            fields.append(("enabled", bool(payload["enabled"])))

        if fields:
            new_version = server_version + 1
            now = _now()
            set_clauses = ", ".join(f"{col}=%s" for col, _ in fields)
            vals = [v for _, v in fields] + [new_version, now, skill_id, uid]
            cur.execute(
                f"UPDATE user_skills SET {set_clauses}, version=%s, updated_at=%s "
                f"WHERE id=%s AND user_id=%s",
                vals,
            )
    return {"ok": True, "skill_id": skill_id}


@router_user_config.delete("/ui/skills/{skill_id}", tags=["WidgetMVP"])
def user_skills_delete(skill_id: str) -> dict[str, Any]:
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM user_skills WHERE id=%s AND user_id=%s", (skill_id, uid))
        if cur.rowcount == 0:
            raise HTTPException(404, "skill_not_found")
    return {"ok": True}


# ═══════════════════════════════════════════
# 4. PREFERENCES
# ═══════════════════════════════════════════


@router_user_config.get("/ui/user-preferences", tags=["WidgetMVP"])
def user_preferences_get() -> dict[str, Any]:
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT key, value, version FROM user_preferences WHERE user_id=%s ORDER BY key",
            (uid,),
        )
        rows = cur.fetchall()
        prefs = {r[0]: r[1] for r in rows}
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM user_preferences WHERE user_id=%s", (uid,))
        version = cur.fetchone()[0]
    return {"preferences": prefs, "version": int(version)}


@router_user_config.put("/ui/user-preferences", tags=["WidgetMVP"])
def user_preferences_put(payload: dict[str, Any]) -> dict[str, Any]:
    """Substitui todas as preferences. Body: { preferences: {...}, version: N }."""
    uid = _user_id()
    prefs = payload.get("preferences", {})
    client_version = payload.get("version", 0)
    source = payload.get("source", "web")

    if not isinstance(prefs, dict):
        raise HTTPException(422, "preferences must be a dict")

    now = _now()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM user_preferences WHERE user_id=%s", (uid,))
        server_version = cur.fetchone()[0]

        if client_version != server_version:
            cur.execute(
                "SELECT key, value FROM user_preferences WHERE user_id=%s ORDER BY key",
                (uid,),
            )
            current = {r[0]: r[1] for r in cur.fetchall()}
            return {
                "error": "version_mismatch",
                "current_version": server_version,
                "your_version": client_version,
                "current_state": {"preferences": current},
            }

        cur.execute("DELETE FROM user_preferences WHERE user_id=%s", (uid,))
        new_version = server_version + 1
        for key, value in prefs.items():
            cur.execute(
                "INSERT INTO user_preferences (user_id, key, value, version, source, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (uid, key, json.dumps(value) if not isinstance(value, str) else value, new_version, source, now),
            )

    return {"ok": True, "version": new_version}


# ═══════════════════════════════════════════
# 4b. PROVIDER ROUTING PREFERENCE (user-level)
# ═══════════════════════════════════════════

# Mapeia routing preference → OpenRouter sort/order params
PROVIDER_ROUTING_MAP: dict[str, dict[str, Any]] = {
    "cheapest": {"sort": "price", "order": None},
    "fastest": {"sort": "latency", "order": None},
    "highest_throughput": {"sort": "throughput", "order": None},
}

DEFAULT_PROVIDER_ROUTING = "cheapest"


def get_user_provider_routing(user_id: str) -> dict[str, Any]:
    """Devolve {sort, order} baseado na preferencia do user. Default: cheapest."""
    try:
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM user_preferences WHERE user_id=%s AND key=%s",
                (user_id, "provider_routing"),
            )
            row = cur.fetchone()
            if row:
                routing = (row[0] or "").strip().strip('"')
                if routing in PROVIDER_ROUTING_MAP:
                    return PROVIDER_ROUTING_MAP[routing]
    except Exception:
        pass
    return PROVIDER_ROUTING_MAP[DEFAULT_PROVIDER_ROUTING]


# ═══════════════════════════════════════════
# 5. TIER PROFILES (per-user model selection)
# ═══════════════════════════════════════════

# Whitelist de providers conhecidos do OpenRouter
KNOWN_OPENROUTER_PROVIDERS = frozenset({
    "DeepSeek", "DeepInfra", "Azure", "Baidu", "Google", "Amazon",
    "Anthropic", "OpenAI", "Together", "Fireworks", "Groq", "Mistral",
    "Novita", "OctoAI", "Perplexity", "Venice", "Nexus",
})

DEFAULT_TIER_PROFILES: dict[str, dict[str, Any]] = {
    "economy": {
        "models": ["openai/gpt-4o-mini", "google/gemini-2.5-flash"],
    },
    "balanced": {
        "models": ["anthropic/claude-sonnet-4", "deepseek/deepseek-v4-pro"],
    },
    "premium": {
        "models": ["anthropic/claude-opus-4", "openai/gpt-4o"],
    },
}


def _ensure_tier_profiles_table(cur: Any) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS user_tier_profiles (
            user_id TEXT NOT NULL,
            tier VARCHAR(20) NOT NULL,
            models JSONB DEFAULT '[]',
            version INT DEFAULT 1,
            updated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, tier)
        );"""
    )


def _validate_providers(providers: list, field: str) -> None:
    for p in providers:
        if p not in KNOWN_OPENROUTER_PROVIDERS:
            raise HTTPException(422, f"provider desconhecido em {field}: {p}")


@router_user_config.get("/ui/tier-profiles", tags=["WidgetMVP"])
def user_tier_profiles_get() -> dict[str, Any]:
    """Devolve os 3 perfis de tier do user (economy, balanced, premium)."""
    uid = _user_id()
    with connect_pg() as conn, conn.cursor() as cur:
        _ensure_tier_profiles_table(cur)
        cur.execute(
            "SELECT tier, models, version "
            "FROM user_tier_profiles WHERE user_id=%s ORDER BY tier",
            (uid,),
        )
        rows = cur.fetchall()
        profiles: dict[str, dict[str, Any]] = {}
        for r in rows:
            profiles[r[0]] = {
                "tier": r[0],
                "models": r[1] or [],
                "version": int(r[2]),
            }

    # Preenche defaults para tiers que o user ainda não configurou
    for tier, defaults in DEFAULT_TIER_PROFILES.items():
        if tier not in profiles:
            profiles[tier] = {**defaults, "tier": tier, "version": 0}

    return {"profiles": profiles}


@router_user_config.put("/ui/tier-profiles/{tier}", tags=["WidgetMVP"])
def user_tier_profiles_put(tier: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Actualiza um perfil de tier do user. Body: { sort?, order_providers?, ... }."""
    if tier not in ("economy", "balanced", "premium"):
        raise HTTPException(422, "tier inválido: economy, balanced, ou premium")

    uid = _user_id()
    client_version = payload.get("version", 0)
    source = payload.get("source", "web")
    now = _now()

    # Validações
    models = payload.get("models")
    if models is not None:
        if not isinstance(models, list) or len(models) == 0:
            raise HTTPException(422, "models deve ser uma lista não vazia")
        if len(models) > 5:
            raise HTTPException(422, "max 5 modelos no fallback chain")

    with connect_pg() as conn, conn.cursor() as cur:
        _ensure_tier_profiles_table(cur)

        # Check version
        cur.execute(
            "SELECT version FROM user_tier_profiles WHERE user_id=%s AND tier=%s",
            (uid, tier),
        )
        row = cur.fetchone()
        server_version = int(row[0]) if row else 0

        if client_version != server_version:
            return {
                "error": "version_mismatch",
                "current_version": server_version,
                "your_version": client_version,
                "tier": tier,
            }

        new_version = server_version + 1
        cur.execute(
            """INSERT INTO user_tier_profiles
               (user_id, tier, models, version, updated_at)
               VALUES (%s, %s, %s::jsonb, %s, %s)
               ON CONFLICT (user_id, tier) DO UPDATE SET
               models = EXCLUDED.models,
               version = EXCLUDED.version,
               updated_at = EXCLUDED.updated_at""",
            (
                uid, tier,
                json.dumps(models) if models else None,
                new_version, now,
            ),
        )

    return {"ok": True, "version": new_version, "tier": tier}


# ═══════════════════════════════════════════
# 6. TIER PROFILES — resolve na inferência
# ═══════════════════════════════════════════

# Modelos homologados para function calling (tools)
TOOLS_CERTIFIED_MODELS = frozenset({
    "openai/gpt-4o", "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4", "anthropic/claude-opus-4",
    "deepseek/deepseek-v4-pro",
    "google/gemini-2.5-pro", "google/gemini-2.5-flash",
})


def get_user_tier_profile(user_id: str, tier: str) -> dict[str, Any] | None:
    """Obtém o perfil de tier do user (apenas models), com fallback para defaults."""
    if tier not in ("economy", "balanced", "premium"):
        return None
    try:
        with connect_pg() as conn, conn.cursor() as cur:
            _ensure_tier_profiles_table(cur)
            cur.execute(
                "SELECT models "
                "FROM user_tier_profiles WHERE user_id=%s AND tier=%s",
                (user_id, tier),
            )
            row = cur.fetchone()
            if row:
                return {
                    "models": row[0] or [],
                }
    except Exception:
        pass
    # Fallback para defaults
    defaults = DEFAULT_TIER_PROFILES.get(tier, {})
    return dict(defaults) if defaults else None


def validate_tools_model_ids(models: list[str]) -> None:
    """Garante que todos os modelos no fallback chain são homologados para tools."""
    for mid in models:
        if mid not in TOOLS_CERTIFIED_MODELS:
            raise ValueError(f"modelo_nao_homologado_para_tools: {mid}")
