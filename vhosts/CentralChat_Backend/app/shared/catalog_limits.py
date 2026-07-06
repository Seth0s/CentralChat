"""Shared limits for team catalog prompts (agents, skills)."""

from __future__ import annotations

import os

# ~16k tokens at ~4 chars/token — enterprise playbooks without dominating 200k context.
_DEFAULT_PROMPT_MAX_CHARS = 64_000


def catalog_prompt_max_chars() -> int:
    raw = os.getenv("CENTRAL_CATALOG_PROMPT_MAX_CHARS", str(_DEFAULT_PROMPT_MAX_CHARS))
    try:
        return max(1000, int(str(raw).strip() or _DEFAULT_PROMPT_MAX_CHARS))
    except (TypeError, ValueError):
        return _DEFAULT_PROMPT_MAX_CHARS


def truncate_catalog_prompt(value: str | None) -> str:
    limit = catalog_prompt_max_chars()
    return (value or "")[:limit]
