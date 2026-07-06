"""Central product pack L0/L1 (Phase 4) — bundled markdown + public snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import config as _cfg

_ORCH_ROOT = Path(__file__).resolve().parent.parent
_CENTRAL_BUNDLED_DIR = _ORCH_ROOT / "bundled" / "central"

CENTRAL_CORE_URI = "central://core@v1"
CENTRAL_CAPABILITIES_URI = "central://capabilities@v1"
CENTRAL_CORE_VERSION = 1
CENTRAL_CAPABILITIES_VERSION = 1


def _read_pack_file(name: str, *, max_bytes: int) -> str:
    path = _CENTRAL_BUNDLED_DIR / name
    if not path.is_file():
        return ""
    raw = path.read_bytes()[: max_bytes + 1]
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", errors="replace").strip()
    if truncated and text:
        text += "\n\n[truncated]"
    return text


def build_central_product_pack_messages() -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    Mensagens system L0/L1 (ADR-014: após âncora L6, antes do bundled legacy).

    Conteúdo breve; tools/schemas só via RAG (D7).
    """
    audit: dict[str, Any] = {
        "central_core_applied": False,
        "central_capabilities_applied": False,
        "central_core_chars": 0,
        "central_capabilities_chars": 0,
        "central_core_uri": CENTRAL_CORE_URI,
        "central_capabilities_uri": CENTRAL_CAPABILITIES_URI,
    }
    if not bool(_cfg.CENTRAL_PRODUCT_PACK_ENABLED):
        return [], audit

    max_b = int(_cfg.CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES)
    msgs: list[dict[str, str]] = []

    core = _read_pack_file("core@v1.md", max_bytes=max_b)
    if core:
        msgs.append(
            {
                "role": "system",
                "content": f"[SYSTEM_CENTRAL_CORE uri={CENTRAL_CORE_URI}]\n{core}",
            }
        )
        audit["central_core_applied"] = True
        audit["central_core_chars"] = len(core)

    caps = _read_pack_file("capabilities@v1.md", max_bytes=max_b)
    if caps:
        msgs.append(
            {
                "role": "system",
                "content": f"[SYSTEM_CENTRAL_CAPABILITIES uri={CENTRAL_CAPABILITIES_URI}]\n{caps}",
            }
        )
        audit["central_capabilities_applied"] = True
        audit["central_capabilities_chars"] = len(caps)

    return msgs, audit


def get_central_product_public_snapshot() -> dict[str, Any]:
    """Snapshot para GET /config (URIs central://)."""
    core_path = _CENTRAL_BUNDLED_DIR / "core@v1.md"
    caps_path = _CENTRAL_BUNDLED_DIR / "capabilities@v1.md"
    return {
        "schema_version": 1,
        "pack_enabled": bool(_cfg.CENTRAL_PRODUCT_PACK_ENABLED),
        "product_rag_enabled": bool(_cfg.CENTRAL_PRODUCT_RAG_ENABLED),
        "tools_only_via_retrieval": bool(_cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL),
        "uris": {
            "core": CENTRAL_CORE_URI,
            "capabilities": CENTRAL_CAPABILITIES_URI,
        },
        "versions": {
            CENTRAL_CORE_URI: CENTRAL_CORE_VERSION,
            CENTRAL_CAPABILITIES_URI: CENTRAL_CAPABILITIES_VERSION,
        },
        "files_present": {
            "core@v1.md": core_path.is_file(),
            "capabilities@v1.md": caps_path.is_file(),
        },
    }
