"""Single source for widget-facing capability flags (Fase 2).

Used by `GET /config` and `GET /ui/inference_catalog` so `widget_feature_flags` never diverges.
"""

from __future__ import annotations

from typing import TypedDict


class WidgetFeatureFlags(TypedDict):
    auto_tier_enabled: bool
    multi_slot_graph_enabled: bool
    composer_segments_in_stream: bool


def get_modality_models_public() -> dict[str, object]:
    """ADR-016 §7 — shared ``modality_models`` block for /config and inference catalog."""
    from app.shared.modality_models import modality_models_public_snapshot

    return modality_models_public_snapshot()


def build_widget_feature_flags(
    *,
    model_router_configured: bool,
    widget_multi_slot_enabled: bool,
    composer_segments_in_stream: bool,
) -> WidgetFeatureFlags:
    """Derive widget feature flags from the same inputs the caller uses for `/config` + catalog."""
    return {
        "auto_tier_enabled": bool(model_router_configured),
        "multi_slot_graph_enabled": bool(widget_multi_slot_enabled),
        "composer_segments_in_stream": bool(composer_segments_in_stream),
    }
