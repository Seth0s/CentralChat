"""When to inject VPS / Central host context into prompts (ADR-017 phase 8)."""
from __future__ import annotations


def include_platform_host_context() -> bool:
    """
    Tenant widget: default off — host summary is the **Central deploy server**, not the user's PC.

    Legacy homelab (``CENTRAL_LEGACY_PLATFORM_TOOLS=1``) keeps previous behaviour.
    """
    from app import config  # noqa: PLC0415

    if config.CENTRAL_LEGACY_PLATFORM_TOOLS:
        return True
    return bool(config.CENTRAL_INCLUDE_PLATFORM_CONTEXT)
