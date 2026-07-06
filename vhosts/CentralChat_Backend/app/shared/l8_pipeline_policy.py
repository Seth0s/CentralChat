"""Pré-Fase 7 — políticas L8 versionadas (JSON opcional + defeitos em código).

Alinha extracto para o router, anexos, summarização, handoff documentado, fallback
planeado e retries HTTP — ver docs/RFC_L8_PIPELINE_V1.md.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import (
    COMPACT_AFTER_CHARS,
    COMPACT_AFTER_MESSAGES,
    COMPACT_KEEP_LAST_MESSAGES,
    L8_PIPELINE_POLICY_PATH,
    PERCEPTION_MAX_IMAGE_BYTES,
)

logger = logging.getLogger(__name__)

_DEFAULT: dict[str, Any] = {
    "schema_version": 1,
    "extract": {
        "router_history_max_messages": 48,
        "router_history_max_chars": 90000,
        "audit_digest_max_chars": 8000,
    },
    "attachments": {
        "max_count": 8,
        "max_base64_chars_per_item": max(PERCEPTION_MAX_IMAGE_BYTES, 4096) * 2 * 2,
        "allowed_mime_prefixes": ["image/", "audio/"],
    },
    "handoff": {
        "merge_required_for_auxiliary": True,
        "phases_documented": ["primary", "perception_aux", "merged"],
    },
    "summarization": {
        "trigger_messages": COMPACT_AFTER_MESSAGES,
        "trigger_chars": COMPACT_AFTER_CHARS,
        "keep_last_messages": COMPACT_KEEP_LAST_MESSAGES,
        "provenance_label": "aux_llm_resolved",
    },
    "fallback": {
        "max_hops": 3,
        "chain": [
            {"step": 0, "note": "resolved_primary_profile"},
            {
                "step": 1,
                "router_profile": "cloud_openai",
                "model_override": "deepseek/deepseek-v4-flash",
                "note": "adr016_fallback_balanced",
            },
            {
                "step": 2,
                "router_profile": "cloud_openai",
                "model_override": "anthropic/claude-sonnet-4.6",
                "note": "adr016_fallback_premium",
            },
        ],
    },
    "transport_retry": {
        "max_attempts": 4,
        "base_delay_ms": 300,
        "max_delay_ms": 8000,
        "jitter_ratio": 0.2,
        "retry_on_status": [429, 503],
        "degrade_auto_tier_on_429": False,
    },
}

_bundle_cache: tuple[str, float, dict[str, Any]] | None = None


def clear_l8_pipeline_policy_cache() -> None:
    global _bundle_cache
    _bundle_cache = None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _file_mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return -2.0


def load_l8_pipeline_policy(*, force_reload: bool = False) -> dict[str, Any]:
    """Política efectiva (defeitos + merge de ficheiro quando válido)."""
    global _bundle_cache
    path = (L8_PIPELINE_POLICY_PATH or "").strip()
    mtime = _file_mtime(path) if path else -1.0
    key = (path, mtime)
    if not force_reload and _bundle_cache is not None and key == (_bundle_cache[0], _bundle_cache[1]):
        return deepcopy(_bundle_cache[2])
    merged = deepcopy(_DEFAULT)
    if path and Path(path).is_file():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("l8_pipeline_policy: read fail %s (%s); defeitos", path, exc)
        else:
            if isinstance(raw, dict):
                merged = _deep_merge(merged, raw)
            else:
                logger.info("l8_pipeline_policy: raiz inesperada em %s; defeitos", path)
    _bundle_cache = (path, mtime, merged)
    return deepcopy(merged)


def get_schema_version() -> int:
    pol = load_l8_pipeline_policy()
    v = pol.get("schema_version")
    return int(v) if isinstance(v, int) else 1


def effective_summarization_thresholds() -> tuple[int, int, int, str]:
    """
    (compact_after_messages, compact_after_chars, keep_last_messages, provenance_label).

    Regra: **gatilho mais cedo** = menor limite (min) entre env legado e política.
    """
    pol = load_l8_pipeline_policy()
    sm = pol.get("summarization") if isinstance(pol.get("summarization"), dict) else {}
    tm = int(sm.get("trigger_messages") or COMPACT_AFTER_MESSAGES)
    tc = int(sm.get("trigger_chars") or COMPACT_AFTER_CHARS)
    kl = int(sm.get("keep_last_messages") or COMPACT_KEEP_LAST_MESSAGES)
    trig_m = min(COMPACT_AFTER_MESSAGES, tm)
    trig_c = min(COMPACT_AFTER_CHARS, tc)
    keep = min(COMPACT_KEEP_LAST_MESSAGES, kl)
    prov = str(sm.get("provenance_label") or "aux_llm_resolved").strip() or "aux_llm_resolved"
    return trig_m, trig_c, keep, prov


def extract_router_caps() -> dict[str, Any]:
    pol = load_l8_pipeline_policy()
    ex = pol.get("extract") if isinstance(pol.get("extract"), dict) else {}
    return {
        "router_history_max_messages": int(ex.get("router_history_max_messages") or 48),
        "router_history_max_chars": int(ex.get("router_history_max_chars") or 90000),
        "audit_digest_max_chars": int(ex.get("audit_digest_max_chars") or 8000),
    }


def transport_retry_config() -> dict[str, Any]:
    pol = load_l8_pipeline_policy()
    tr = pol.get("transport_retry") if isinstance(pol.get("transport_retry"), dict) else {}
    statuses = tr.get("retry_on_status")
    if not isinstance(statuses, list):
        statuses = [429, 503]
    st_set = {int(x) for x in statuses if isinstance(x, int) or (isinstance(x, str) and str(x).isdigit())}
    if not st_set:
        st_set = {429, 503}
    return {
        "max_attempts": max(1, int(tr.get("max_attempts") or 4)),
        "base_delay_ms": max(50, int(tr.get("base_delay_ms") or 300)),
        "max_delay_ms": max(100, int(tr.get("max_delay_ms") or 8000)),
        "jitter_ratio": min(0.9, max(0.0, float(tr.get("jitter_ratio") or 0.2))),
        "retry_on_status": st_set,
        "degrade_auto_tier_on_429": bool(tr.get("degrade_auto_tier_on_429")),
    }


def fallback_chain_preview() -> list[dict[str, Any]]:
    pol = load_l8_pipeline_policy()
    fb = pol.get("fallback") if isinstance(pol.get("fallback"), dict) else {}
    chain = fb.get("chain")
    if not isinstance(chain, list):
        return list(_DEFAULT["fallback"]["chain"])
    out: list[dict[str, Any]] = []
    for item in chain:
        if isinstance(item, dict):
            out.append({k: item[k] for k in item if isinstance(k, str)})
    return out or list(_DEFAULT["fallback"]["chain"])


def fallback_max_hops() -> int:
    pol = load_l8_pipeline_policy()
    fb = pol.get("fallback") if isinstance(pol.get("fallback"), dict) else {}
    return max(1, int(fb.get("max_hops") or 3))


def build_stream_fallback_attempts(
    primary_profile: str,
    primary_model_override: str | None,
) -> list[tuple[str, str | None, str]]:
    """
    Tentativas (perfil, model_override, nota) para o stream NDJSON principal.

    Sempre inclui o par resolvido; acrescenta ``router_profile`` da cadeia L8 até
    ``max_hops`` tentativas no total (dedupe por perfil+override).
    """
    hops = fallback_max_hops()
    prof0 = primary_profile.strip()
    attempts: list[tuple[str, str | None, str]] = [
        (prof0, primary_model_override, "resolved_primary"),
    ]
    seen: set[tuple[str, str]] = {(prof0, (primary_model_override or "").strip())}
    for entry in fallback_chain_preview():
        if len(attempts) >= hops:
            break
        if not isinstance(entry, dict):
            continue
        rp = entry.get("router_profile")
        if not isinstance(rp, str) or not rp.strip():
            continue
        rp = rp.strip()
        mo_raw = entry.get("model_override")
        mo2: str | None = None
        if isinstance(mo_raw, str) and mo_raw.strip():
            mo2 = mo_raw.strip()
        key = (rp, mo2 or "")
        if key in seen:
            continue
        seen.add(key)
        note = str(entry.get("note") or "policy_fallback").strip() or "policy_fallback"
        attempts.append((rp, mo2, note))
    return attempts[:hops]


def handoff_defaults() -> dict[str, Any]:
    pol = load_l8_pipeline_policy()
    h = pol.get("handoff") if isinstance(pol.get("handoff"), dict) else {}
    return {
        "merge_required_for_auxiliary": bool(h.get("merge_required_for_auxiliary", True)),
        "phases_documented": h.get("phases_documented")
        if isinstance(h.get("phases_documented"), list)
        else list(_DEFAULT["handoff"]["phases_documented"]),
    }


def build_l8_inference_meta(
    *,
    injection_meta: dict[str, Any],
    perception_text_block: bool,
) -> dict[str, Any]:
    hb = handoff_defaults()
    return {
        "schema_version": get_schema_version(),
        "handoff": {
            "phase": "perception_aux" if perception_text_block else "primary",
            "merge_required_for_auxiliary": hb["merge_required_for_auxiliary"],
            "phases_documented": hb["phases_documented"],
            "perception_augmentation": bool(perception_text_block),
        },
        "fallback_chain": fallback_chain_preview(),
        "router_extract": injection_meta.get("l8_router_extract"),
    }
