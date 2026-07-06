"""Validação de anexos multimodais contra política L8."""

from __future__ import annotations

from typing import Any

from app.config import CENTRAL_VIDEO_MAX_BASE64_CHARS
from app.shared.l8_pipeline_policy import load_l8_pipeline_policy


def validate_media_attachments(attachments: list[Any]) -> None:
    """Levanta ``ValueError`` com código estável se os limites forem violados."""
    if not attachments:
        return
    pol = load_l8_pipeline_policy()
    sec = pol.get("attachments") if isinstance(pol.get("attachments"), dict) else {}
    max_count = max(1, int(sec.get("max_count") or 8))
    max_chars = max(1024, int(sec.get("max_base64_chars_per_item") or 4_194_304))
    prefixes_raw = sec.get("allowed_mime_prefixes")
    if isinstance(prefixes_raw, list) and prefixes_raw:
        prefixes = [str(p).lower() for p in prefixes_raw if isinstance(p, str) and p.strip()]
    else:
        prefixes = ["image/", "audio/", "video/"]
    if "video/" not in prefixes:
        prefixes = [*prefixes, "video/"]

    max_video_chars = max(
        max_chars,
        int(sec.get("max_video_base64_chars") or CENTRAL_VIDEO_MAX_BASE64_CHARS),
    )

    if len(attachments) > max_count:
        raise ValueError(f"attachments_too_many:{len(attachments)}>{max_count}")

    video_count = 0
    for i, a in enumerate(attachments):
        raw = str(getattr(a, "data_base64", "") or "").strip()
        mime = str(getattr(a, "mime", "") or "").strip().lower()
        kind = str(getattr(a, "kind", "") or "").strip().lower()
        is_video = kind == "video" or mime.startswith("video/")
        if is_video:
            video_count += 1
            if len(raw) > max_video_chars:
                raise ValueError(f"attachment_too_large:{i}")
        elif len(raw) > max_chars:
            raise ValueError(f"attachment_too_large:{i}")
        if not any(mime.startswith(p) for p in prefixes):
            raise ValueError(f"attachment_mime_not_allowed:{i}:{mime}")

    if video_count > 1:
        raise ValueError(f"attachments_too_many_videos:{video_count}>1")
