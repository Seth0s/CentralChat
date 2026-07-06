"""
Multimodal perception (ADR-016): attachments → structured text for the primary brain.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.shared.attachment_policy import validate_media_attachments
from app.clients import call_model_router_raw_messages
from app.config import PERCEPTION_MAX_IMAGE_BYTES
from app.shared.modality_models import (
    ROLE_AUDIO_PERCEIVE,
    ROLE_VIDEO_PERCEIVE,
    ROLE_VISION_PERCEIVE,
    modality_model_display_label,
    resolve_modality_call_params,
)
from app.shared.video_frames import extract_video_frames_base64, ffmpeg_available


class MediaAttachment(BaseModel):
    kind: Literal["image", "audio", "video"] = "image"
    mime: str = Field(default="image/png", max_length=120)
    data_base64: str = Field(..., min_length=8, description="Base64 payload (no data: prefix)")


def _perception_instruction(user_text: str) -> str:
    return (
        "Tarefa: descrever com fidelidade o conteúdo visual ou referido nos anexos.\n"
        "Regras:\n"
        "- Não inventes factos; só o que é legível ou audível.\n"
        "- Responde em português, em bullets curtos quando fizer sentido.\n"
        "- Mascara segredos como [REDACTED].\n\n"
        f"Pedido do utilizador (contexto): {user_text.strip()}\n"
    )


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


def resolve_perception_modality_role(attachments: list[MediaAttachment]) -> str:
    """Pick vision vs video vs audio role from attachment kinds."""
    if any(a.kind == "image" for a in attachments):
        return ROLE_VISION_PERCEIVE
    if any(a.kind == "video" for a in attachments):
        return ROLE_VIDEO_PERCEIVE
    if any(a.kind == "audio" for a in attachments):
        return ROLE_AUDIO_PERCEIVE
    return ROLE_VISION_PERCEIVE


def resolve_perception_call_params(
    attachments: list[MediaAttachment],
) -> tuple[str, str, str]:
    """Return ``(modality_role, router_profile, model_id)``."""
    role = resolve_perception_modality_role(attachments)
    profile, model_id = resolve_modality_call_params(role)
    return role, profile, model_id


def _build_multimodal_parts(
    user_text: str,
    attachments: list[MediaAttachment],
) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = [{"type": "text", "text": _perception_instruction(user_text)}]
    approx_b64_cap = max(PERCEPTION_MAX_IMAGE_BYTES, 4096) * 2

    for a in attachments:
        raw = a.data_base64.strip()
        if len(raw) > approx_b64_cap:
            raise ValueError("attachment_too_large")
        if a.kind == "image":
            url = f"data:{a.mime};base64,{raw}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            parts.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": raw,
                        "format": _mime_to_audio_format(a.mime),
                    },
                }
            )
    return parts


def _perceive_single_image_frame(
    user_text: str,
    frame_b64: str,
    *,
    frame_index: int,
    frame_total: int,
    profile: str,
    model_override: str,
) -> str:
    """One vision call for a sampled JPEG frame (ADR-016 §13)."""
    prompt = (
        f"Quadro {frame_index}/{frame_total} de um vídeo. "
        "Descreve apenas o que é visível neste quadro, em português, em bullets curtos. "
        "Não inventes áudio ou acções fora do frame.\n\n"
        f"Pedido do utilizador (contexto geral): {user_text.strip()}"
    )
    url = f"data:image/jpeg;base64,{frame_b64.strip()}"
    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    return call_model_router_raw_messages(
        messages,
        profile=profile,
        model_override=model_override,
        allowlist_mode="modality",
    ).strip()


def _aggregate_video_frame_notes(
    user_text: str,
    frame_notes: list[str],
    *,
    profile: str,
    model_override: str,
) -> str:
    """Merge per-frame vision notes into one summary (text-only; video_perceive model)."""
    joined = "\n".join(f"- {n}" for n in frame_notes if n.strip())
    prompt = (
        "Tarefa: sintetizar observações de vários quadros amostrados de um vídeo curto.\n"
        "Regras: português; parágrafo ou bullets; não inventes factos além das notas; "
        "menciona incerteza se os quadros forem ambíguos.\n\n"
        f"Pedido do utilizador: {user_text.strip()}\n\n"
        f"Notas por quadro:\n{joined}"
    )
    messages: list[dict[str, object]] = [{"role": "user", "content": prompt}]
    return call_model_router_raw_messages(
        messages,
        profile=profile,
        model_override=model_override,
        allowlist_mode="modality",
    ).strip()


def _build_video_perception_block(user_text: str, videos: list[MediaAttachment]) -> str:
    if not videos:
        return ""
    if not ffmpeg_available():
        return "[Percepção vídeo indisponível: ffmpeg não encontrado no servidor.]\n"

    vision_profile, vision_model = resolve_modality_call_params(ROLE_VISION_PERCEIVE)
    video_profile, video_model = resolve_modality_call_params(ROLE_VIDEO_PERCEIVE)

    label = modality_model_display_label(video_model)
    all_notes: list[str] = []

    for vid in videos:
        try:
            frames = extract_video_frames_base64(vid.data_base64, mime=vid.mime)
        except ValueError as exc:
            code = str(exc)
            return f"[Percepção vídeo: falha ao amostrar quadros ({code}).]\n"

        frame_notes: list[str] = []
        total = len(frames)
        for idx, fb64 in enumerate(frames, start=1):
            note = _perceive_single_image_frame(
                user_text,
                fb64,
                frame_index=idx,
                frame_total=total,
                profile=vision_profile,
                model_override=vision_model,
            )
            frame_notes.append(note)

        if len(frame_notes) == 1:
            all_notes.append(frame_notes[0])
        else:
            all_notes.append(
                _aggregate_video_frame_notes(
                    user_text,
                    frame_notes,
                    profile=video_profile,
                    model_override=video_model,
                )
            )

    body = "\n\n".join(n.strip() for n in all_notes if n.strip())
    return f"[Percepção vídeo {label}]\n{body}"


def build_perception_enriched_block(
    user_text: str,
    attachments: list[MediaAttachment],
    *,
    profile: str | None = None,
    model_override: str | None = None,
    modality_role: str | None = None,
) -> str:
    """
    Call the configured perception model with multimodal messages; return block to prefix the user turn.
    When ``profile`` / ``model_override`` are omitted, resolves via ADR-016 modality roles.
    """
    if not attachments:
        return ""
    validate_media_attachments(attachments)

    videos = [a for a in attachments if a.kind == "video"]
    non_video = [a for a in attachments if a.kind != "video"]
    blocks: list[str] = []
    if videos:
        blocks.append(_build_video_perception_block(user_text, videos))
    if not non_video:
        return "\n".join(b for b in blocks if b)

    attachments = non_video
    role = modality_role or resolve_perception_modality_role(attachments)
    if profile is None or model_override is None:
        resolved_profile, resolved_model = resolve_modality_call_params(role)
        profile = profile or resolved_profile
        model_override = model_override or resolved_model
    else:
        profile = profile or "balanced"
        model_override = model_override or None

    label = modality_model_display_label(model_override or role)
    parts = _build_multimodal_parts(user_text, attachments)
    messages: list[dict[str, object]] = [{"role": "user", "content": parts}]
    reply = call_model_router_raw_messages(
        messages,
        profile=profile,
        model_override=model_override,
        allowlist_mode="modality",
    )
    blocks.append(f"[Percepção {label}]\n{reply.strip()}")
    return "\n\n".join(b for b in blocks if b)
