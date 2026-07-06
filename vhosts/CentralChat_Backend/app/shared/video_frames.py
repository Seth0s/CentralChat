"""ADR-016 §13 — sample video clips to JPEG frames (ffmpeg); never send full video to the LLM."""
from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import CENTRAL_VIDEO_MAX_DURATION_SEC, CENTRAL_VIDEO_MAX_FRAMES

logger = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").strip().lower().split(";", 1)[0]
    if m == "video/mp4":
        return ".mp4"
    if m == "video/webm":
        return ".webm"
    if m.startswith("video/"):
        ext = m.split("/", 1)[1]
        if ext in ("mp4", "webm", "quicktime", "x-matroska"):
            return f".{ext.replace('x-matroska', 'mkv')}"
    return ".mp4"


def extract_video_frames_base64(
    data_base64: str,
    *,
    mime: str,
    max_frames: int | None = None,
    max_duration_sec: float | None = None,
) -> list[str]:
    """
    Decode base64 video, extract up to ``max_frames`` JPEG stills with ffmpeg.

    Raises ``ValueError`` with stable codes (``ffmpeg_not_available``, ``video_decode_failed``,
    ``video_extract_failed``).
    """
    if not ffmpeg_available():
        raise ValueError("ffmpeg_not_available")

    raw_b64 = (data_base64 or "").strip()
    if len(raw_b64) < 8:
        raise ValueError("video_decode_failed:empty")

    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError("video_decode_failed:invalid_base64") from exc

    if not blob:
        raise ValueError("video_decode_failed:empty_bytes")

    n_frames = max(1, min(int(max_frames or CENTRAL_VIDEO_MAX_FRAMES), 24))
    duration_cap = max(1.0, float(max_duration_sec or CENTRAL_VIDEO_MAX_DURATION_SEC))
    fps = max(0.05, n_frames / duration_cap)

    suffix = _suffix_for_mime(mime)
    frames_out: list[str] = []

    with tempfile.TemporaryDirectory(prefix="central-video-") as td:
        td_path = Path(td)
        inp = td_path / f"input{suffix}"
        inp.write_bytes(blob)
        pattern = td_path / "frame_%03d.jpg"

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(inp),
            "-t",
            str(duration_cap),
            "-vf",
            f"fps={fps},scale='min(640,iw)':-2",
            "-q:v",
            "4",
            "-frames:v",
            str(n_frames),
            str(pattern),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("video_extract_failed:timeout") from exc
        except OSError as exc:
            raise ValueError("video_extract_failed:spawn") from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:400]
            logger.info("video_frames: ffmpeg failed rc=%s err=%s", proc.returncode, err)
            raise ValueError(f"video_extract_failed:ffmpeg:{proc.returncode}")

        for path in sorted(td_path.glob("frame_*.jpg")):
            try:
                frames_out.append(base64.b64encode(path.read_bytes()).decode("ascii"))
            except OSError as exc:
                raise ValueError("video_extract_failed:read_frame") from exc

    if not frames_out:
        raise ValueError("video_extract_failed:no_frames")

    return frames_out
