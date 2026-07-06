"""ADR-016 — OpenRouter audio: TTS (direct API) and STT capability probes."""
from __future__ import annotations

import base64
import logging
import re
import uuid
from pathlib import Path

import httpx

from app.config import (
    CENTRAL_ROOT,
    CENTRAL_TTS_MODEL_ID,
    DISABLE_STT,
    DISABLE_TTS,
    MODEL_ROUTER_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_TTS_RESPONSE_FORMAT,
    OPENROUTER_TTS_SPEECH_URL,
    OPENROUTER_TTS_VOICE,
    SECRETS_VAULT_PATH,
    STT_SERVICE_URL,
    TTS_SERVICE_URL,
)
from app.shared.local_vault import resolve_secret
from app.shared.modality_models import ROLE_AUDIO_PERCEIVE, ROLE_TTS, resolve_modality_call_params, resolve_modality_model_id

logger = logging.getLogger(__name__)


def _mime_to_audio_format(mime: str) -> str:
    m = (mime or "").strip().lower().split(";", 1)[0]
    if m in ("audio/wav", "audio/x-wav", "audio/wave"):
        return "wav"
    if m in ("audio/mpeg", "audio/mp3"):
        return "mp3"
    if m == "audio/webm":
        return "webm"
    if m == "audio/ogg":
        return "ogg"
    if m.startswith("audio/"):
        return m.split("/", 1)[1] or "wav"
    return "wav"


def _stt_instruction() -> str:
    return (
        "Transcreva integralmente o áudio anexo em português.\n"
        "Regras:\n"
        "- Responda apenas com o texto falado, sem prefixos nem comentários.\n"
        "- Mascara segredos como [REDACTED].\n"
    )


def transcribe_audio_bytes(
    file_bytes: bytes,
    *,
    content_type: str = "audio/wav",
) -> str:
    """STT via audio_perceive — multimodal (model-router or direct OpenRouter)."""
    if not file_bytes:
        return ""
    from app.clients import call_model_router_raw_messages

    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    profile, model_id = resolve_modality_call_params(ROLE_AUDIO_PERCEIVE)
    mime = content_type or "audio/wav"
    parts: list[dict[str, object]] = [
        {"type": "text", "text": _stt_instruction()},
        {
            "type": "input_audio",
            "input_audio": {"data": b64, "format": _mime_to_audio_format(mime)},
        },
    ]
    messages: list[dict[str, object]] = [{"role": "user", "content": parts}]
    reply = call_model_router_raw_messages(
        messages,
        profile=profile,
        model_override=model_id,
        allowlist_mode="modality",
    )
    return reply.strip()

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")


def resolve_openrouter_api_key() -> str:
    """Env ``OPENROUTER_API_KEY`` then vault key ``openrouter_api_key`` (if allowlisted)."""
    return resolve_secret(
        env_value=OPENROUTER_API_KEY,
        vault_path=SECRETS_VAULT_PATH,
        vault_key="openrouter_api_key",
    )


def openrouter_tts_configured() -> bool:
    if DISABLE_TTS:
        return False
    if not resolve_openrouter_api_key():
        return False
    try:
        resolve_modality_model_id(ROLE_TTS)
        return True
    except ValueError:
        return bool(CENTRAL_TTS_MODEL_ID.strip())


def openrouter_stt_configured() -> bool:
    if DISABLE_STT:
        return False
    if not resolve_openrouter_api_key():
        return False
    try:
        resolve_modality_model_id(ROLE_AUDIO_PERCEIVE)
        return True
    except ValueError:
        return False


def legacy_stt_configured() -> bool:
    return bool((STT_SERVICE_URL or "").strip()) and not DISABLE_STT


def legacy_tts_configured() -> bool:
    return bool((TTS_SERVICE_URL or "").strip()) and not DISABLE_TTS


def _sanitize_filename(name: str | None, *, default_ext: str) -> str:
    raw = (name or "").strip() or f"tts_{uuid.uuid4().hex[:12]}.{default_ext}"
    base = _FILENAME_SAFE.sub("_", raw).strip("._") or f"out.{default_ext}"
    if "." not in base:
        base = f"{base}.{default_ext}"
    return base[:200]


def _audio_output_dir() -> Path:
    root = (CENTRAL_ROOT or "").strip()
    if root:
        out = Path(root) / "state" / "audio"
    else:
        out = Path("/tmp/central_audio")
    out.mkdir(parents=True, exist_ok=True)
    return out


def synthesize_speech_openrouter(text: str, *, filename: str | None = None) -> str:
    """
    POST OpenRouter TTS; write bytes under ``{CENTRAL_ROOT}/state/audio/``.

    Returns absolute path to the audio file.
    """
    api_key = resolve_openrouter_api_key()
    if not api_key:
        raise RuntimeError("openrouter_api_key_missing")
    model_id = resolve_modality_model_id(ROLE_TTS)
    body = {
        "model": model_id,
        "input": (text or "").strip(),
        "voice": (OPENROUTER_TTS_VOICE or "alloy").strip() or "alloy",
        "response_format": (OPENROUTER_TTS_RESPONSE_FORMAT or "mp3").strip() or "mp3",
    }
    if not body["input"]:
        return ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = (OPENROUTER_TTS_SPEECH_URL or "https://openrouter.ai/api/v1/audio/speech").strip()
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        audio_bytes = response.content
    ext = str(body["response_format"]).lower()
    out_name = _sanitize_filename(filename, default_ext=ext)
    out_path = _audio_output_dir() / out_name
    out_path.write_bytes(audio_bytes)
    return str(out_path.resolve())


def stack_health_stt_entry() -> dict[str, object]:
    if DISABLE_STT:
        return {"status": "disabled"}
    if openrouter_stt_configured():
        try:
            mid = resolve_modality_model_id(ROLE_AUDIO_PERCEIVE)
        except ValueError:
            mid = ""
        return {
            "status": "ok",
            "backend": "openrouter",
            "via": "model_router" if (MODEL_ROUTER_URL or "").strip() else "direct",
            "model_id": mid,
            "legacy_url_configured": bool((STT_SERVICE_URL or "").strip()),
        }
    if legacy_stt_configured():
        return {
            "status": "deprecated",
            "backend": "legacy_microservice",
            "detail": "STT_SERVICE_URL; prefer OpenRouter audio_perceive (ADR-016)",
            "url": STT_SERVICE_URL.strip().rstrip("/"),
        }
    return {"status": "skipped", "detail": "not_configured"}


def stack_health_tts_entry() -> dict[str, object]:
    if DISABLE_TTS:
        return {"status": "disabled"}
    if openrouter_tts_configured():
        try:
            mid = resolve_modality_model_id(ROLE_TTS)
        except ValueError:
            mid = ""
        return {
            "status": "ok",
            "backend": "openrouter",
            "model_id": mid,
            "legacy_url_configured": bool((TTS_SERVICE_URL or "").strip()),
        }
    if legacy_tts_configured():
        return {
            "status": "deprecated",
            "backend": "legacy_microservice",
            "detail": "TTS_SERVICE_URL; prefer OpenRouter TTS (ADR-016)",
            "url": TTS_SERVICE_URL.strip().rstrip("/"),
        }
    return {"status": "skipped", "detail": "not_configured"}
