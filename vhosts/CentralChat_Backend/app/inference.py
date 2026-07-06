"""Inference domain — model router client, catalog, allowlist, profiles, routing, inference resolution.

Consolidated from:
  - model_router_http_client.py    (HTTP client for model-router)
  - model_router_transport.py      (retries with backoff + jitter)
  - model_router_vendor_models.py  (vendor catalog fetch)
  - vendor_catalog_cache.py        (in-process TTL cache)
  - model_router_client.py         (router public config cache)
  - cloud_models_allowlist.py      (allowlist CRUD + resolve)
  - auto_tier_policies.py          (auto-tier economy/balanced/premium)
  - inference_context.py           (effective context window cap)
  - inference_model_gate.py        (model_override gate)
  - inference_routing.py           (inference_routing.json loader)
  - inference_resolve.py           (LLM call params resolution)
  - inference.py                   (API router)
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import (
    CENTRAL_CONTEXT_WINDOW_CAP,
    CENTRAL_ROOT,
    CENTRAL_RATE_LIMIT_ENABLED,
    CENTRAL_RATE_LIMIT_PATH_PREFIXES,
    CENTRAL_RATE_LIMIT_PER_WINDOW,
    CENTRAL_RATE_LIMIT_WINDOW_SECONDS,
    CLOUD_ROUTER_PROFILE,
    COMPOSER_SEGMENTS_IN_STREAM_ENABLED,
    INFERENCE_ROUTING_PATH,
    MODEL_ROUTER_HTTP_CONNECT_TIMEOUT_SECONDS,
    MODEL_ROUTER_HTTP_READ_TIMEOUT_SECONDS,
    MODEL_ROUTER_URL,
    VENDOR_CATALOG_CACHE_TTL_SECONDS,
    WIDGET_MULTI_SLOT_ENABLED,
)
from app.shared.modality_models import resolve_modality_call_params
from app.shared.profiles import (
    PROFILES,
    get_active_profile,
    router_profile_for_agent_tools,
    router_profile_for_ui_profile,
    set_active_profile,
)
from app.shared.public_capabilities import build_widget_feature_flags, get_modality_models_public
from app.repositories.preferences_repository import load_preferences
from app.shared.system_prompt_manifest import get_system_prompt_public_snapshot

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# MODEL ROUTER HTTP CLIENT
# ═══════════════════════════════════════════════════════════════════


def router_base_url() -> str:
    return (MODEL_ROUTER_URL or "").strip().rstrip("/")


def _router_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=MODEL_ROUTER_HTTP_CONNECT_TIMEOUT_SECONDS,
        read=MODEL_ROUTER_HTTP_READ_TIMEOUT_SECONDS,
        write=MODEL_ROUTER_HTTP_READ_TIMEOUT_SECONDS,
        pool=5.0,
    )


def _classify_http_exception(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "router_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "router_connect_error"
    if isinstance(exc, httpx.NetworkError):
        return "router_network_error"
    if isinstance(exc, httpx.RequestError):
        return "router_request_error"
    return "router_http_error"


def router_get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    """
    GET JSON no model-router.
    path deve começar por ``/`` (ex.: ``/config``, ``/openai/models``).
    Devolve ``(body, None)`` em sucesso, ou ``(None, código)`` com código estável.
    """
    base = router_base_url()
    if not base:
        return None, "no_url"
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    try:
        with httpx.Client(timeout=_router_timeout()) as client:
            r = client.get(url, params=params)
    except httpx.RequestError as exc:
        code = _classify_http_exception(exc)
        logger.info("model_router GET fail path=%s code=%s err=%s", path, code, exc)
        return None, code
    except Exception as exc:  # noqa: BLE001
        logger.info("model_router GET unexpected path=%s err=%s", path, exc)
        return None, "router_request_error"
    if r.status_code != 200:
        logger.info("model_router GET path=%s status=%s", path, r.status_code)
        return None, f"http_{r.status_code}"
    if not (r.content and r.content.strip()):
        return None, "empty_body"
    try:
        data = r.json()
    except Exception:
        return None, "invalid_json"
    if isinstance(data, (dict, list)):
        return data, None
    return None, "invalid_json"


# ═══════════════════════════════════════════════════════════════════
# MODEL ROUTER TRANSPORT (retries with backoff + jitter)
# ═══════════════════════════════════════════════════════════════════


def backoff_sleep(attempt: int, base_ms: int, max_ms: int, jitter_ratio: float) -> None:
    exp = min(max_ms, int(base_ms * (2**attempt)))
    j = max(0.0, min(0.95, jitter_ratio))
    factor = 1.0 - j + random.random() * (2 * j)
    time.sleep((exp * max(0.05, factor)) / 1000.0)


def execute_with_http_retries(
    op: Callable[[], Any],
    *,
    max_attempts: int,
    retry_statuses: set[int],
    base_delay_ms: int,
    max_delay_ms: int,
    jitter_ratio: float,
) -> Any:
    """
    Reexecuta ``op`` em códigos configuráveis (defeito 429/503).
    ``op`` deve devolver ``httpx.Response`` com corpo já lido ou stream aberto.
    """
    last_exc: BaseException | None = None
    for attempt in range(max(1, max_attempts)):
        try:
            return op()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            last_exc = exc
            if code in retry_statuses and attempt < max_attempts - 1:
                backoff_sleep(attempt, base_delay_ms, max_delay_ms, jitter_ratio)
                continue
            raise
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                backoff_sleep(attempt, base_delay_ms, max_delay_ms, jitter_ratio)
                continue
            raise


# ═══════════════════════════════════════════════════════════════════
# MODEL ROUTER VENDOR MODELS (vendor catalog from /openai/models)
# ═══════════════════════════════════════════════════════════════════


def _normalize_vendor_model_id(model_id: str) -> str:
    mid = (model_id or "").strip()
    if not mid:
        return ""
    if mid.startswith("models/"):
        return mid[len("models/") :].strip()
    return mid


def _row_from_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, dict):
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return None
        norm = _normalize_vendor_model_id(raw_id)
        if not norm:
            return None
        label_raw = item.get("label")
        if isinstance(label_raw, str) and label_raw.strip():
            label = label_raw.strip()
        else:
            label = norm
        return {"id": norm, "label": label}
    if isinstance(item, str) and item.strip():
        norm = _normalize_vendor_model_id(item)
        if norm:
            return {"id": norm, "label": norm}
    return None


def fetch_vendor_catalog_from_router(
    router_profile: str,
    *,
    refresh: bool = False,
) -> tuple[list[dict[str, str]] | None, str | None]:
    params: dict[str, Any] = {"profile": router_profile.strip()}
    if refresh:
        params["refresh"] = "true"
    data, err = router_get_json("/openai/models", params=params)
    if err is not None:
        return None, err[:400]
    if not isinstance(data, dict):
        return None, "invalid_json"
    raw = data.get("models")
    if not isinstance(raw, list):
        return None, "campo_models_ausente"
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        row = _row_from_item(item)
        if row is None:
            continue
        rid = row["id"]
        if rid in seen:
            continue
        seen.add(rid)
        rows.append(row)
    return rows, None


def fetch_vendor_model_ids_from_router(
    router_profile: str,
    *,
    refresh: bool = False,
) -> tuple[list[str] | None, str | None]:
    rows, err = fetch_vendor_catalog_from_router(router_profile, refresh=refresh)
    if err is not None:
        return None, err
    if rows is None:
        return None, None
    return [r["id"] for r in rows], None


# ═══════════════════════════════════════════════════════════════════
# VENDOR CATALOG CACHE (in-process TTL cache)
# ═══════════════════════════════════════════════════════════════════

_vendor_cache_lock = threading.Lock()
_vendor_cache: dict[str, dict[str, Any]] = {}


def get_vendor_catalog_cached(
    router_profile: str,
    *,
    refresh: bool,
) -> tuple[list[dict[str, str]] | None, str | None]:
    prof = (router_profile or "").strip() or "cloud_openai"
    if refresh:
        rows, err = fetch_vendor_catalog_from_router(prof, refresh=True)
        with _vendor_cache_lock:
            if err is None and rows is not None:
                _vendor_cache[prof] = {"rows": rows, "fetched_at": time.monotonic()}
            else:
                _vendor_cache.pop(prof, None)
        return rows, err

    now = time.monotonic()
    with _vendor_cache_lock:
        ent = _vendor_cache.get(prof)
        if ent and (now - float(ent["fetched_at"])) < float(VENDOR_CATALOG_CACHE_TTL_SECONDS):
            return [dict(x) for x in ent["rows"]], None

    rows, err = fetch_vendor_catalog_from_router(prof, refresh=False)
    with _vendor_cache_lock:
        if err is None and rows is not None:
            _vendor_cache[prof] = {"rows": rows, "fetched_at": time.monotonic()}
        else:
            _vendor_cache.pop(prof, None)
    return rows, err


# ═══════════════════════════════════════════════════════════════════
# MODEL ROUTER CLIENT (router public config cache)
# ═══════════════════════════════════════════════════════════════════

_router_config_cache: dict[str, Any] | None = None
_router_config_cache_at: float = 0.0
_ROUTER_CONFIG_TTL_SEC = 30.0


def get_model_router_public_config(*, force_refresh: bool = False) -> dict[str, Any]:
    """Devolve o JSON de ``{MODEL_ROUTER_URL}/config`` ou ``{}`` se indisponível."""
    global _router_config_cache, _router_config_cache_at
    now = time.monotonic()
    if not force_refresh and _router_config_cache is not None and (now - _router_config_cache_at) < _ROUTER_CONFIG_TTL_SEC:
        return _router_config_cache
    body, _err = router_get_json("/config")
    _router_config_cache = body if isinstance(body, dict) else {}
    _router_config_cache_at = now
    return _router_config_cache or {}


# ═══════════════════════════════════════════════════════════════════
# CLOUD MODELS (per-user via user_cloud_models table)
# ═══════════════════════════════════════════════════════════════════

_ID_SAFE = re.compile(r"^[A-Za-z0-9._\-/:]{1,256}$")


def row_effective_enabled(row: dict[str, Any]) -> bool:
    if "enabled" not in row:
        return True
    v = row.get("enabled")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return bool(v)


def load_cloud_models_catalog(user_id: str | None = None) -> list[dict[str, Any]]:
    """Retorna modelos enabled do user da tabela user_cloud_models.

    Sem user_id: retorna lista vazia (modo full_vendor — qualquer ID
    com formato válido é permitido na validação de inferência).
    """
    if not user_id:
        return []
    try:
        from app.shared.pg_tenant import connect_pg

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT model_id, label, enabled FROM user_cloud_models "
                "WHERE user_id=%s AND enabled=true ORDER BY model_id",
                (user_id,),
            )
            return [
                {"id": r[0], "label": r[1], "enabled": r[2]} for r in cur.fetchall()
            ]
    except Exception:
        return []


def is_model_id_allowed(model_id: str, catalog: list[dict[str, Any]]) -> bool:
    """Full_vendor mode: qualquer ID com formato válido é permitido.

    Se houver catálogo (modelos do user), verifica se o modelo está
    enabled. Modelos fora do catálogo são permitidos por defeito.
    """
    if not catalog:
        return bool(_ID_SAFE.match(model_id))
    for x in catalog:
        if str(x.get("id") or "") == model_id:
            return row_effective_enabled(x)
    return bool(_ID_SAFE.match(model_id))


def validate_llm_model_id_shape(model_id: str) -> bool:
    return bool(_ID_SAFE.match((model_id or "").strip()))


# ═══════════════════════════════════════════════════════════════════
# AUTO TIER POLICIES (simplified — per-user tier profiles in user_config.py)
# ═══════════════════════════════════════════════════════════════════

VALID_AUTO_TIERS = frozenset({"economy", "balanced", "premium"})


def auto_tier_policies_public_snapshot() -> dict[str, Any]:
    """Snapshot legado para /config — tier profiles agora são per-user."""
    return {
        "schema_version": 3,
        "tiers": {
            "economy": {"pick": "first"},
            "balanced": {"pick": "middle"},
            "premium": {"pick": "last"},
        },
        "provider_routing": "user_preferences (key: provider_routing, values: cheapest|fastest|highest_throughput)",
        "source": "per-user (user_tier_profiles + user_preferences)",
    }


# ═══════════════════════════════════════════════════════════════════
# INFERENCE CONTEXT (effective context window cap)
# ═══════════════════════════════════════════════════════════════════

_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "openai/gpt-4o-mini": 128_000,
}


def effective_inference_context_cap(model_override: str | None) -> int:
    product_cap = max(1, int(CENTRAL_CONTEXT_WINDOW_CAP or 200_000))
    mid = (model_override or "").strip()
    if not mid:
        return product_cap
    model_limit = _MODEL_CONTEXT_LIMITS.get(mid)
    if model_limit is not None:
        return min(product_cap, model_limit)
    return product_cap


# ═══════════════════════════════════════════════════════════════════
# INFERENCE MODEL GATE
# ═══════════════════════════════════════════════════════════════════

AllowlistMode = Literal["ui", "modality"]

ADR16_DEV_UI_ALLOWLIST_SAMPLE: frozenset[str] = frozenset({
    "deepseek/deepseek-v4-flash:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-20b:free",
})


def validate_outbound_model_router_override(model_override: str | None, *, allowlist_mode: AllowlistMode = "ui") -> None:
    """Validação de modelo: apenas shape check (full_vendor mode).

    A allowlist per-user é aplicada no momento de selecção (UI),
    não na inferência. Qualquer modelo com ID válido é aceite.
    """
    if not model_override:
        return
    mid = model_override.strip()
    if not validate_llm_model_id_shape(mid):
        raise RuntimeError("llm_model_id_formato_invalido")


def validate_ui_model_router_override(model_override: str | None) -> None:
    validate_outbound_model_router_override(model_override, allowlist_mode="ui")


def validate_modality_model_router_override(model_override: str | None) -> None:
    validate_outbound_model_router_override(model_override, allowlist_mode="modality")


# ═══════════════════════════════════════════════════════════════════
# INFERENCE ROUTING
# ═══════════════════════════════════════════════════════════════════


def load_inference_routing() -> dict[str, Any] | None:
    path = (INFERENCE_ROUTING_PATH or "").strip()
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


# ═══════════════════════════════════════════════════════════════════
# INFERENCE RESOLVE
# ═══════════════════════════════════════════════════════════════════

_UI_SLUG = {"A": "eco", "B": "balanced", "C": "quality"}


def _available_profiles_from_router(router_public: dict[str, Any]) -> frozenset[str] | None:
    if not router_public:
        return None
    pl = router_public.get("profiles")
    if not isinstance(pl, list):
        return None
    s = frozenset(str(p) for p in pl if p)
    return s if s else None


def _local_router_candidates(ui_key: str, routing: dict[str, Any] | None) -> list[str]:
    k = (ui_key or "").strip().upper()
    out: list[str] = []
    if routing:
        local = routing.get("local")
        if isinstance(local, dict) and k in local:
            out.append(str(local[k]))
    slug = _UI_SLUG.get(k, "balanced")
    out.append(f"local_{slug}")
    out.append(slug)
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        x = x.strip()
        if not x or x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _pick_first_available(candidates: list[str], available: frozenset[str] | None, default_profile: str) -> str:
    if available:
        for c in candidates:
            if c in available:
                return c
        if default_profile in available:
            return default_profile
        return next(iter(sorted(available)))
    if candidates:
        return candidates[0]
    return default_profile


def _resolve_current_user_id() -> str | None:
    """Extrai user_id do contexto JWT actual, se disponível."""
    try:
        from app.shared.tenant_context import get_current_sub

        return get_current_sub()
    except Exception:
        return None


def resolve_llm_call_params(*, active_ui_profile: str, prefs: dict[str, Any], router_public: dict[str, Any]) -> tuple[str, str | None]:
    dest = str(prefs.get("inference_destination") or "local").strip().lower()
    if dest not in ("local", "api"):
        dest = "local"
    routing = load_inference_routing()
    available = _available_profiles_from_router(router_public)
    default_prof = str(router_public.get("default_profile") or "balanced")
    if dest == "local":
        candidates = _local_router_candidates(active_ui_profile, routing)
        profile = _pick_first_available(candidates, available, default_prof)
        if available and profile not in available:
            profile = router_profile_for_ui_profile(active_ui_profile)
            if profile not in available:
                profile = _pick_first_available([default_prof], available, default_prof)
        return profile, None
    if not (MODEL_ROUTER_URL or "").strip():
        # Sem model-router: perfil cloud com fallback directo OpenRouter
        api_profile = str(CLOUD_ROUTER_PROFILE).strip() or "cloud_openai"
    else:
        api_block = routing.get("api") if routing else None
        api_name = None
        if isinstance(api_block, dict):
            api_name = api_block.get("router_profile")
        api_profile = str(api_name or CLOUD_ROUTER_PROFILE).strip() or CLOUD_ROUTER_PROFILE
        if available and api_profile not in available:
            raise ValueError(f"perfil_router_api_desconhecido:{api_profile}")
    raw_mid = str(prefs.get("llm_model_id") or "").strip()
    tier = str(prefs.get("auto_tier") or "").strip().lower()
    model_override: str | None
    if raw_mid:
        model_override = raw_mid
        if not validate_llm_model_id_shape(model_override):
            raise ValueError("llm_model_id_formato_invalido")
    elif tier in VALID_AUTO_TIERS:
        # Auto-tier: usa models[0] do tier profile (ou fallback catalog)
        user_id = _resolve_current_user_id()
        if user_id:
            try:
                from app.user_config import get_user_tier_profile

                tp = get_user_tier_profile(user_id, tier)
                if tp and tp.get("models"):
                    model_override = tp["models"][0]
                else:
                    catalog = load_cloud_models_catalog(user_id)
                    ids = sorted(set(m["id"] for m in catalog if m.get("id")))
                    model_override = ids[0] if ids else None
            except Exception:
                model_override = None
        else:
            model_override = None
    else:
        model_override = None
    return api_profile, model_override


def resolve_aux_llm_call_params(*, prefs: dict[str, Any], router_public: dict[str, Any]) -> tuple[str, str | None]:
    dest = str(prefs.get("aux_llm_destination") or "local").strip().lower()
    if dest not in ("local", "api"):
        dest = "local"
    available = _available_profiles_from_router(router_public)
    default_prof = str(router_public.get("default_profile") or "balanced")
    if dest == "local":
        candidates = ["local_eco", "eco"]
        profile = _pick_first_available(candidates, available, default_prof)
        return profile, None
    if not (MODEL_ROUTER_URL or "").strip():
        raise ValueError("aux_inference_api_requer_MODEL_ROUTER_URL")
    api_profile, model_override = resolve_modality_call_params("summary")
    if available and api_profile not in available:
        raise ValueError(f"perfil_router_aux_api_desconhecido:{api_profile}")
    return api_profile, model_override


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_inference = APIRouter()


class ProfileRequest(BaseModel):
    profile: str = Field(..., description="A | B | C")


class CloudModelAllowlistEntry(BaseModel):
    id: str = Field(..., min_length=1, max_length=256)
    label: str = Field(default="", max_length=512)
    enabled: bool = Field(default=True, description="False = mantido na lista mas inactivo para o model-router")


class CloudModelsAllowlistWriteRequest(BaseModel):
    models: list[CloudModelAllowlistEntry] = Field(default_factory=list, max_length=5000)


def _api_backend_allows_model_override(router_public: dict[str, Any], api_profile: str) -> bool:
    if not router_public or not api_profile:
        return False
    backends = router_public.get("profile_backends")
    if not isinstance(backends, dict):
        return False
    entry = backends.get(api_profile)
    if not isinstance(entry, dict):
        return False
    caps = entry.get("capabilities")
    if not isinstance(caps, dict):
        return False
    return bool(caps.get("allow_model_override"))


def _ui_inference_snapshot() -> dict[str, Any]:
    prefs = load_preferences()
    pub = get_model_router_public_config()
    try:
        eff, mo = resolve_llm_call_params(active_ui_profile=get_active_profile(), prefs=prefs, router_public=pub)
        err: str | None = None
    except ValueError as exc:
        eff = router_profile_for_ui_profile(get_active_profile())
        mo = None
        err = str(exc)
    dest = str(prefs.get("inference_destination") or "local")
    api_prof = CLOUD_ROUTER_PROFILE
    rt = load_inference_routing()
    if rt and isinstance(rt.get("api"), dict):
        v = rt["api"].get("router_profile")
        if v:
            api_prof = str(v).strip()
    mo_allowed = bool(pub and _api_backend_allows_model_override(pub, api_prof))
    return {
        "inference_destination": dest,
        "llm_model_id": str(prefs.get("llm_model_id") or ""),
        "auto_tier": str(prefs.get("auto_tier") or ""),
        "provider_routing": str(prefs.get("provider_routing") or ""),
        "effective_router_profile": eff,
        "active_model_override": mo,
        "inference_resolve_error": err,
        "api_router_profile": api_prof,
        "cloud_models": [],  # per-user models agora via /ui/cloud-models
        "model_router_configured": bool((MODEL_ROUTER_URL or "").strip()),
        "allow_model_override_for_api_profile": mo_allowed,
    }


def _require_resolved_llm() -> tuple[str, str, str | None]:
    prefs = load_preferences()
    pub = get_model_router_public_config()
    try:
        router_profile, model_override = resolve_llm_call_params(
            active_ui_profile=get_active_profile(), prefs=prefs, router_public=pub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if model_override and pub and not _api_backend_allows_model_override(pub, router_profile):
        raise HTTPException(status_code=400, detail="model_override_nao_permitido_para_o_perfil_cloud")
    tools_profile = router_profile_for_agent_tools(router_profile)
    return tools_profile, router_profile, model_override


def resolve_llm_for_assistant_request(
    payload: Any | None = None,
) -> tuple[str, str, str | None]:
    """Resolve LLM params; optional per-request model_override (session-scoped)."""
    tools_profile, router_profile, model_override = _require_resolved_llm()
    if payload is None:
        return tools_profile, router_profile, model_override
    req_override = str(getattr(payload, "model_override", None) or "").strip()
    if not req_override:
        return tools_profile, router_profile, model_override
    if not validate_llm_model_id_shape(req_override):
        raise HTTPException(status_code=400, detail="llm_model_id_formato_invalido")
    try:
        from app.shared.inference_governance import assert_model_allowed

        assert_model_allowed(req_override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pub = get_model_router_public_config()
    if pub and not _api_backend_allows_model_override(pub, router_profile):
        raise HTTPException(status_code=400, detail="model_override_nao_permitido_para_o_perfil_cloud")
    return tools_profile, router_profile, req_override


def _sorted_vendor_rows_for_ui(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda r: (str(r.get("label") or r.get("id") or "").lower(), str(r.get("id") or "").lower()))


def _norm_vendor_q(raw: str | None) -> str:
    return (raw or "").strip()[:120]


@router_inference.get("/ui/profiles", tags=["OpsDashboard"])
def ui_profiles() -> dict:
    active = get_active_profile()
    return {"active_profile": active, "profiles": PROFILES}


@router_inference.post("/ui/profile", tags=["DeprecatedWidget", "OpsDashboard"])
def ui_profile_set(payload: ProfileRequest) -> dict[str, str]:
    try:
        active = set_active_profile(payload.profile.upper())
        return {"active_profile": active}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── (legacy /ui/inference_catalog and /ui/cloud_models_allowlist removed in M4 —
#     replaced by per-user endpoints in user_config.py) ──

