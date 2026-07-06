"""Preferências do assistente (merge persistente em disco)."""

from __future__ import annotations

from app.shared.assistant_preferences import (
    default_preferences,
    load_preferences,
    merge_preferences_patch,
    preferences_system_messages,
)

__all__ = [
    "default_preferences",
    "load_preferences",
    "merge_preferences_patch",
    "preferences_system_messages",
]
