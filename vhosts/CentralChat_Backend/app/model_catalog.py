"""Model Catalog — caches context_length from provider APIs.

OpenRouter, Anthropic, OpenAI all expose context_length in their model
list endpoints. We cache this and use it for dynamic compaction thresholds.

Compaction: threshold = model.context_length * 0.5 (50% of context window).
This is per-model, not a global env var.

Design: docs discussion — compaction is per-model, derived at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PATH = Path(os.getenv("CENTRAL_ROOT", Path.home() / ".central")) / "cache" / "model_catalog.json"
CACHE_TTL_SECONDS = 3600  # 1 hour

# Known model defaults (fallback when API unavailable)
_MODEL_DEFAULTS: dict[str, int] = {
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "openai/gpt-4-turbo": 128_000,
    "openai/gpt-3.5-turbo": 16_385,
    "anthropic/claude-sonnet-4": 200_000,
    "anthropic/claude-opus-4": 200_000,
    "anthropic/claude-haiku-3.5": 200_000,
    "google/gemini-2.5-pro": 1_048_576,
    "google/gemini-2.5-flash": 1_048_576,
    "google/gemini-2.0-flash": 1_048_576,
    "deepseek/deepseek-chat": 128_000,
    "deepseek/deepseek-reasoner": 64_000,
    "meta-llama/llama-4-maverick": 128_000,
    "meta-llama/llama-4-scout": 256_000,
    "qwen/qwen-max": 32_768,
}

# Context window percentage threshold for compaction
COMPACTION_RATIO = 0.5  # compact at 50% of context window


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def get_context_length(model_id: str) -> int:
    """Get context window size for a model.
    
    Tries: cached → API fallback → hardcoded default → safe minimum.
    """
    cache = _load_cache()
    
    # Check cache
    if model_id in cache:
        entry = cache[model_id]
        if time.time() - entry.get("cached_at", 0) < CACHE_TTL_SECONDS:
            return entry["context_length"]
    
    # Try provider API
    length = _fetch_from_api(model_id)
    if length:
        cache[model_id] = {"context_length": length, "cached_at": time.time()}
        _save_cache(cache)
        return length
    
    # Hardcoded fallback
    for pattern, cl in _MODEL_DEFAULTS.items():
        if pattern in model_id.lower():
            return cl
    
    # Safe minimum
    logger.warning("Unknown model %s — using default 32K context", model_id)
    return 32_768


def get_compaction_threshold(model_id: str) -> int:
    """Tokens at which to trigger compaction for this model."""
    return int(get_context_length(model_id) * COMPACTION_RATIO)


def get_keep_recent_tokens(model_id: str) -> int:
    """Tokens to keep as verbatim tail after compaction."""
    return int(get_context_length(model_id) * 0.15)  # 15% tail


def refresh_catalog() -> dict[str, int]:
    """Force-refresh the model catalog from provider APIs."""
    cache = {}
    for provider_url, parser in _PROVIDERS:
        try:
            models = parser(provider_url)
            cache.update(models)
        except Exception as exc:
            logger.debug("Model catalog refresh failed for %s: %s", provider_url, exc)
    
    # Merge hardcoded fallbacks for models not in API
    for model_id, cl in _MODEL_DEFAULTS.items():
        if model_id not in cache:
            cache[model_id] = cl
    
    _save_cache({m: {"context_length": cl, "cached_at": time.time()} for m, cl in cache.items()})
    return cache


# ═══════════════════════════════════════════════════════════════
# Provider API fetchers
# ═══════════════════════════════════════════════════════════════

def _fetch_openrouter_models(api_key: str | None = None) -> dict[str, int]:
    """Fetch models from OpenRouter API (free, no auth needed for list)."""
    import urllib.request
    
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    headers = {}
    if key and key != "***":
        headers["Authorization"] = f"Bearer {key}"
    
    req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    
    models = {}
    for m in data.get("data", []):
        model_id = m.get("id", "")
        cl = m.get("context_length", 0)
        if model_id and cl:
            models[model_id] = cl
    return models


def _fetch_openai_models(api_key: str | None = None) -> dict[str, int]:
    """Fetch from OpenAI API (needs key). OpenAI doesn't expose context_length directly in list, use known values."""
    return {}  # OpenAI v1/models doesn't return context_length — use hardcoded


def _fetch_anthropic_models(api_key: str | None = None) -> dict[str, int]:
    """Anthropic doesn't have a public model list API — use hardcoded."""
    return {}


# Provider list: (label, fetcher)
_PROVIDERS: list[tuple[str, Any]] = [
    ("openrouter", _fetch_openrouter_models),
]


# ═══════════════════════════════════════════════════════════════
# Cache I/O
# ═══════════════════════════════════════════════════════════════

def _load_cache() -> dict[str, dict[str, Any]]:
    if CACHE_PATH.is_file():
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def _fetch_from_api(model_id: str) -> int | None:
    """Try to find model in provider APIs."""
    cache = {}
    for _, fetcher in _PROVIDERS:
        try:
            models = fetcher()
            cache.update(models)
        except Exception:
            pass
    
    if cache:
        _save_cache({m: {"context_length": cl, "cached_at": time.time()} for m, cl in cache.items()})
        return cache.get(model_id)
    return None
