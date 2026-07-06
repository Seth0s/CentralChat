"""ADR-016 — resolve modality role → OpenRouter model id (env → JSON → built-in defaults)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

from app import config as app_config
from app.config import MODALITY_MODELS_PATH

logger = logging.getLogger(__name__)

ROLE_SUMMARY: Final = "summary"
ROLE_VISION_PERCEIVE: Final = "vision_perceive"
ROLE_AUDIO_PERCEIVE: Final = "audio_perceive"
ROLE_TTS: Final = "tts"
ROLE_WEB_RESEARCH_FAST: Final = "web_research_fast"
ROLE_WEB_RESEARCH_DEFAULT: Final = "web_research_default"
ROLE_WEB_RESEARCH_DEEP: Final = "web_research_deep"
ROLE_SOCIAL_COPY: Final = "social_copy"
ROLE_SOCIAL_COPY_PREMIUM: Final = "social_copy_premium"
ROLE_IMAGE_GENERATE: Final = "image_generate"
ROLE_VIDEO_PERCEIVE: Final = "video_perceive"
ROLE_OCR_DENSE: Final = "ocr_dense"

KNOWN_MODALITY_ROLES: Final = frozenset(
    {
        ROLE_SUMMARY,
        ROLE_VISION_PERCEIVE,
        ROLE_AUDIO_PERCEIVE,
        ROLE_TTS,
        ROLE_WEB_RESEARCH_FAST,
        ROLE_WEB_RESEARCH_DEFAULT,
        ROLE_WEB_RESEARCH_DEEP,
        ROLE_SOCIAL_COPY,
        ROLE_SOCIAL_COPY_PREMIUM,
        ROLE_IMAGE_GENERATE,
        ROLE_VIDEO_PERCEIVE,
        ROLE_OCR_DENSE,
    }
)

_ROLE_ALIASES: dict[str, str] = {
    "web_research": ROLE_WEB_RESEARCH_DEFAULT,
}

# Camada B — inferência via model-router usa perfil auxiliar (ADR-016 §6–8).
_AUX_ROUTER_ROLES: frozenset[str] = frozenset(
    {
        ROLE_SUMMARY,
        ROLE_VISION_PERCEIVE,
        ROLE_AUDIO_PERCEIVE,
        ROLE_WEB_RESEARCH_FAST,
        ROLE_WEB_RESEARCH_DEFAULT,
        ROLE_WEB_RESEARCH_DEEP,
        ROLE_SOCIAL_COPY,
        ROLE_SOCIAL_COPY_PREMIUM,
        ROLE_IMAGE_GENERATE,
        ROLE_VIDEO_PERCEIVE,
        ROLE_OCR_DENSE,
    }
)

def _env_model_id_for_role(canon: str) -> str:
    """Read env override at resolve time (tests may patch ``app.config``)."""
    attr_by_role = {
        ROLE_SUMMARY: "CENTRAL_SUMMARY_MODEL_ID",
        ROLE_VISION_PERCEIVE: "CENTRAL_VISION_PERCEIVE_MODEL_ID",
        ROLE_AUDIO_PERCEIVE: "CENTRAL_AUDIO_PERCEIVE_MODEL_ID",
        ROLE_TTS: "CENTRAL_TTS_MODEL_ID",
        ROLE_WEB_RESEARCH_DEFAULT: "CENTRAL_WEB_RESEARCH_MODEL_ID",
        ROLE_WEB_RESEARCH_FAST: "CENTRAL_WEB_RESEARCH_MODEL_ID_FAST",
        ROLE_WEB_RESEARCH_DEEP: "CENTRAL_WEB_RESEARCH_MODEL_ID_DEEP",
        ROLE_SOCIAL_COPY: "CENTRAL_SOCIAL_COPY_MODEL_ID",
        ROLE_SOCIAL_COPY_PREMIUM: "CENTRAL_SOCIAL_COPY_MODEL_ID_PREMIUM",
        ROLE_IMAGE_GENERATE: "CENTRAL_IMAGE_GENERATE_MODEL_ID",
        ROLE_VIDEO_PERCEIVE: "CENTRAL_VIDEO_PERCEIVE_MODEL_ID",
    }
    attr = attr_by_role.get(canon)
    if not attr:
        return ""
    raw = getattr(app_config, attr, "")
    return str(raw or "").strip()

_ROLE_LABELS_PT: dict[str, str] = {
    ROLE_SUMMARY: "Resumo / compactação",
    ROLE_VISION_PERCEIVE: "Percepção visual",
    ROLE_AUDIO_PERCEIVE: "Percepção de áudio",
    ROLE_TTS: "Texto para voz (TTS)",
    ROLE_WEB_RESEARCH_FAST: "Pesquisa web (rápida)",
    ROLE_WEB_RESEARCH_DEFAULT: "Pesquisa web",
    ROLE_WEB_RESEARCH_DEEP: "Pesquisa web (profunda)",
    ROLE_SOCIAL_COPY: "Copy para redes sociais",
    ROLE_SOCIAL_COPY_PREMIUM: "Copy para redes (premium)",
    ROLE_IMAGE_GENERATE: "Geração de imagem",
    ROLE_VIDEO_PERCEIVE: "Percepção de vídeo",
    ROLE_OCR_DENSE: "OCR denso",
}

_BUILTIN_DEFAULTS: dict[str, dict[str, str]] = {
    "production": {
        ROLE_SUMMARY: "google/gemini-2.5-flash-lite",
        ROLE_VISION_PERCEIVE: "google/gemini-2.5-flash-lite",
        ROLE_AUDIO_PERCEIVE: "google/gemini-2.5-flash-lite",
        ROLE_TTS: "openai/gpt-4o-mini-tts-2025-12-15",
        ROLE_WEB_RESEARCH_FAST: "perplexity/sonar",
        ROLE_WEB_RESEARCH_DEFAULT: "perplexity/sonar-pro",
        ROLE_WEB_RESEARCH_DEEP: "perplexity/sonar-deep-research",
        ROLE_SOCIAL_COPY: "x-ai/grok-4.1-fast",
        ROLE_SOCIAL_COPY_PREMIUM: "google/gemini-2.5-flash",
        ROLE_IMAGE_GENERATE: "google/gemini-2.5-flash-image",
        ROLE_VIDEO_PERCEIVE: "qwen/qwen3.6-flash",
        ROLE_OCR_DENSE: "baidu/qianfan-ocr-fast",
    },
    "development": {
        ROLE_SUMMARY: "google/gemma-4-26b-a4b-it:free",
        ROLE_VISION_PERCEIVE: "google/gemma-4-26b-a4b-it:free",
        ROLE_AUDIO_PERCEIVE: "google/gemma-4-26b-a4b-it:free",
        ROLE_TTS: "openai/gpt-4o-mini-tts-2025-12-15",
        ROLE_WEB_RESEARCH_DEFAULT: "perplexity/sonar",
        ROLE_SOCIAL_COPY: "x-ai/grok-4.1-fast",
        ROLE_IMAGE_GENERATE: "google/gemini-2.5-flash-image",
    },
}

_bundle_cache: tuple[str, float, dict[str, str], str] | None = None


def clear_modality_models_cache() -> None:
    """Tests: invalidate in-process JSON cache."""
    global _bundle_cache
    _bundle_cache = None


def _active_config_env() -> str:
    env = (app_config.CENTRAL_APP_ENV or "development").strip().lower()
    if env in ("production", "prod"):
        return "production"
    return "development"


def _file_mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return -2.0


def canonical_modality_role(role: str) -> str:
    """Normalize role slug; map aliases (e.g. web_research → web_research_default)."""
    key = (role or "").strip().lower()
    if not key:
        raise ValueError("modality_role_vazio")
    return _ROLE_ALIASES.get(key, key)


def _builtin_default_for_role(role: str, *, config_env: str | None = None) -> str | None:
    block = _BUILTIN_DEFAULTS.get(config_env or _active_config_env(), {})
    mid = block.get(role)
    if isinstance(mid, str) and mid.strip():
        return mid.strip()
    prod = _BUILTIN_DEFAULTS.get("production", {})
    fallback = prod.get(role)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def load_modality_models_map(*, force_reload: bool = False) -> tuple[dict[str, str], str]:
    """
    Return ``(role → model_id, source)`` for the active CENTRAL_APP_ENV block.

    ``source`` is ``file`` when read from JSON, else ``default`` (built-ins only).
    """
    global _bundle_cache
    path = (MODALITY_MODELS_PATH or "").strip()
    mtime = _file_mtime(path) if path else -1.0
    if (
        not force_reload
        and _bundle_cache is not None
        and (path, mtime) == (_bundle_cache[0], _bundle_cache[1])
    ):
        return _bundle_cache[2], _bundle_cache[3]

    config_env = _active_config_env()
    merged: dict[str, str] = {}
    source = "default"

    if path and Path(path).is_file():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("modality_models: failed to read %s (%s); using built-in defaults", path, exc)
        else:
            if isinstance(raw, dict):
                block = raw.get(config_env)
                if isinstance(block, dict):
                    for k, v in block.items():
                        if not isinstance(k, str) or not isinstance(v, str):
                            continue
                        mid = v.strip()
                        if mid:
                            merged[k.strip().lower()] = mid
                    if merged:
                        source = "file"
            else:
                logger.info("modality_models: unexpected JSON root in %s; built-in defaults", path)

    _bundle_cache = (path, mtime, merged, source)
    return merged, source


def resolve_modality_model_id(role: str) -> str:
    """
    Resolve OpenRouter model id for a modality role.

    Precedence: env ``CENTRAL_*_MODEL_ID`` → ``modality_models.json`` → built-in ADR defaults.
    """
    canon = canonical_modality_role(role)
    if canon not in KNOWN_MODALITY_ROLES:
        raise ValueError(f"modality_role_desconhecido:{canon}")

    env_val = _env_model_id_for_role(canon)
    if env_val:
        from app.inference import validate_llm_model_id_shape

        if not validate_llm_model_id_shape(env_val):
            raise ValueError(f"modality_model_id_formato_invalido:{canon}")
        return env_val

    file_map, _ = load_modality_models_map()
    from_file = (file_map.get(canon) or "").strip()
    if from_file:
        from app.inference import validate_llm_model_id_shape

        if not validate_llm_model_id_shape(from_file):
            raise ValueError(f"modality_model_id_formato_invalido:{canon}")
        return from_file

    builtin = _builtin_default_for_role(canon)
    if builtin:
        return builtin

    raise ValueError(f"modality_model_id_nao_configurado:{canon}")


def resolve_modality_router_profile(role: str) -> str:
    """Router profile for model-router calls (aux vs primary cloud profile)."""
    canon = canonical_modality_role(role)
    if canon in _AUX_ROUTER_ROLES:
        return (app_config.AUX_CLOUD_ROUTER_PROFILE or "cloud_gemini").strip() or "cloud_gemini"
    if canon == ROLE_TTS:
        return (app_config.AUX_CLOUD_ROUTER_PROFILE or "cloud_gemini").strip() or "cloud_gemini"
    return (app_config.CLOUD_ROUTER_PROFILE or "cloud_openai").strip() or "cloud_openai"


def modality_model_display_label(model_id: str) -> str:
    """Short human label for SSE / enriched blocks (slug after vendor prefix)."""
    mid = (model_id or "").strip()
    if not mid:
        return "modality"
    if "/" in mid:
        return mid.split("/", 1)[1]
    return mid


def resolve_modality_call_params(role: str) -> tuple[str, str]:
    """Return ``(router_profile, model_override)`` for a modality role."""
    canon = canonical_modality_role(role)
    return resolve_modality_router_profile(canon), resolve_modality_model_id(canon)


def _resolution_source_for_role(canon: str, file_map: dict[str, str]) -> str:
    if _env_model_id_for_role(canon):
        return "env"
    if (file_map.get(canon) or "").strip():
        return "json"
    return "default"


_COMPOSER_LABEL_SHORT: dict[str, str] = {
    ROLE_VISION_PERCEIVE: "Percepção",
    ROLE_AUDIO_PERCEIVE: "Percepção",
    ROLE_WEB_RESEARCH_FAST: "Pesquisa",
    ROLE_WEB_RESEARCH_DEFAULT: "Pesquisa",
    ROLE_WEB_RESEARCH_DEEP: "Pesquisa",
    ROLE_SOCIAL_COPY: "Copy",
    ROLE_SOCIAL_COPY_PREMIUM: "Copy",
    ROLE_IMAGE_GENERATE: "Imagem",
    ROLE_SUMMARY: "Resumo",
    ROLE_VIDEO_PERCEIVE: "Percepção",
    ROLE_OCR_DENSE: "OCR",
}


def modality_composer_label(role: str) -> str:
    """Short PT label for ``composer_segments`` auxiliary rows (ADR-016 §7)."""
    canon = canonical_modality_role(role)
    return _COMPOSER_LABEL_SHORT.get(canon, _ROLE_LABELS_PT.get(canon, "Auxiliar"))


def build_modality_invocation_entry(
    *,
    modality_role: str,
    model_id: str,
    phase: str,
) -> dict[str, str]:
    """One row for ``inference_meta.modality_invocations`` (no binary payloads)."""
    canon = canonical_modality_role(modality_role)
    return {
        "modality_role": canon,
        "model_id": (model_id or "").strip(),
        "label_pt": modality_composer_label(canon),
        "phase": (phase or "").strip(),
    }


_MODALITY_AGENT_TOOL_NAMES: frozenset[str] = frozenset(
    {"web_research", "draft_social_post", "generate_post_image"}
)


def record_modality_invocation_from_tool_result(
    invocations: list[dict[str, str]],
    *,
    tool_name: str,
    result: Any,
    phase: str | None = None,
) -> None:
    """Append invocation telemetry after a modality agent tool runs."""
    if tool_name.strip() not in _MODALITY_AGENT_TOOL_NAMES:
        return
    if not isinstance(result, dict):
        return
    role = str(result.get("modality_role") or "").strip()
    model_id = str(result.get("model_id") or "").strip()
    if not role:
        return
    invocations.append(
        build_modality_invocation_entry(
            modality_role=role,
            model_id=model_id,
            phase=phase or f"tool:{tool_name.strip()}",
        )
    )


def modality_models_public_snapshot() -> dict[str, Any]:
    """Read-only snapshot for GET /config and GET /ui/inference_catalog."""
    file_map, file_source = load_modality_models_map()
    config_env = _active_config_env()
    roles_out: list[dict[str, str]] = []
    for role in sorted(KNOWN_MODALITY_ROLES):
        try:
            model_id = resolve_modality_model_id(role)
        except ValueError:
            continue
        roles_out.append(
            {
                "role": role,
                "model_id": model_id,
                "label_pt": _ROLE_LABELS_PT.get(role, role),
                "source": _resolution_source_for_role(role, file_map),
            }
        )
    return {
        "schema_version": 1,
        "environment": config_env,
        "file_source": file_source,
        "roles": roles_out,
    }
