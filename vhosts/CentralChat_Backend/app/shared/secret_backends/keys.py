"""Logical key helpers shared across secret backends."""

from __future__ import annotations


def normalize_logical_key(key: str) -> str:
    return (key or "").strip().lower()


def is_provider_key(key: str) -> bool:
    return normalize_logical_key(key).startswith("provider:")


def provider_id_from_key(key: str) -> str:
    return normalize_logical_key(key).split(":", 1)[1]


def provider_logical_key(provider_id: str) -> str:
    return f"provider:{provider_id.strip().lower()}"


def storage_segment(logical_key: str) -> str:
    """Convert logical key to a path-safe segment (no colons)."""
    return normalize_logical_key(logical_key).replace(":", "/")


def custom_value_filename(logical_key: str) -> str:
    return normalize_logical_key(logical_key).replace(":", "__")
