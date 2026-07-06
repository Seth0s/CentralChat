"""
Metadados do SYSTEM versionado (paths, hashes, origem efectiva) + ordem de composição ADR-014.

O conteúdo injectado no LLM é construído em :mod:`app.system_prompt_loader` (Fase 11).
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from app import config as _cfg

_lock = threading.Lock()
_snap_startup: dict[str, Any] | None = None
_snap_poll: dict[str, Any] | None = None
_snap_poll_key: tuple[int, int] | None = None

COMPOSITION_ORDER: list[str] = [
    "l6_policy",
    "bundled_system_md",
    "overlay_system_md",
    "user_preferences",
    "history_multislot_canvas",
]


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return -1


def _fingerprint(path: Path, *, max_bytes: int | None) -> tuple[bool, int, str]:
    """exists, bytes_read, sha256 hex first 16 chars."""
    if not path.is_file():
        return False, 0, ""
    total = 0
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            if max_bytes is not None:
                rem = max_bytes - total
                if rem <= 0:
                    break
                if len(chunk) > rem:
                    chunk = chunk[:rem]
            h.update(chunk)
            total += len(chunk)
            if max_bytes is not None and total >= max_bytes:
                break
    return True, total, h.hexdigest()[:16]


def _build_snapshot_unlocked() -> dict[str, Any]:
    bundled_path = Path(_cfg.CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH).expanduser()
    raw_overlay = (_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH or "").strip()
    overlay_path = Path(raw_overlay).expanduser() if raw_overlay else None

    b_ex, b_n, b_h = _fingerprint(bundled_path, max_bytes=_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES)
    o_ex = False
    o_n = 0
    o_h = ""
    if overlay_path is not None:
        o_ex, o_n, o_h = _fingerprint(overlay_path, max_bytes=_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES)

    if o_ex and o_n > 0:
        effective_origin = "central_root_overlay"
    elif b_ex and b_n > 0:
        effective_origin = "bundled"
    else:
        effective_origin = "none"

    return {
        "schema_version": 1,
        "bundled_id": _cfg.CENTRAL_SYSTEM_PROMPT_BUNDLED_ID,
        "bundled_version": int(_cfg.CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION),
        "bundled_path": str(bundled_path),
        "bundled_present": bool(b_ex and b_n > 0),
        "bundled_bytes": int(b_n),
        "bundled_content_sha256_16": b_h,
        "overlay_path": str(overlay_path) if overlay_path is not None else "",
        "overlay_present": bool(o_ex and o_n > 0),
        "overlay_bytes": int(o_n),
        "overlay_content_sha256_16": o_h,
        "overlay_max_bytes": int(_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES),
        "effective_origin": effective_origin,
        "reload_mode": str(_cfg.CENTRAL_SYSTEM_PROMPT_RELOAD_MODE),
        "reload_poll_seconds": int(_cfg.CENTRAL_SYSTEM_PROMPT_MTIME_POLL_SECONDS),
        "composition_order": list(COMPOSITION_ORDER),
    }


def get_system_prompt_public_snapshot() -> dict[str, Any]:
    """Snapshot estável para `/config`, `ui_trace` e `inference_meta` (com cache)."""
    global _snap_startup, _snap_poll, _snap_poll_key
    bundled_path = Path(_cfg.CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH).expanduser()
    raw_overlay = (_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH or "").strip()
    overlay_path = Path(raw_overlay).expanduser() if raw_overlay else None

    with _lock:
        if _cfg.CENTRAL_SYSTEM_PROMPT_RELOAD_MODE == "startup_only":
            if _snap_startup is not None:
                return dict(_snap_startup)
            _snap_startup = _build_snapshot_unlocked()
            return dict(_snap_startup)

        om = _mtime_ns(overlay_path) if overlay_path is not None else -2
        key = (_mtime_ns(bundled_path), om)
        if _snap_poll is not None and _snap_poll_key == key:
            return dict(_snap_poll)
        _snap_poll = _build_snapshot_unlocked()
        _snap_poll_key = key
        return dict(_snap_poll)


def reset_system_prompt_cache_for_tests() -> None:
    """Testes apenas."""
    global _snap_startup, _snap_poll, _snap_poll_key
    with _lock:
        _snap_startup = None
        _snap_poll = None
        _snap_poll_key = None
