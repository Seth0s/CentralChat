"""T11 — OpenRouter direct LLM client (runs on connector or VPS).

Replaces model-router service. Uses OPENROUTER_API_KEY directly.
Supports: chat completions, streaming (SSE), tool_calls, fallback chain,
provider routing, middle-out transforms, provider transparency.
Reuses T6 circuit breaker for resilience.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

import httpx

from app.config import OPENROUTER_API_KEY

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# ═══ OpenRouter Server Tools (processed server-side, zero local code) ═══

DEFAULT_OPENROUTER_TOOLS: list[dict[str, str]] = [
    # Server tools desabilitadas temporariamente — debugging 500
    # {"type": "openrouter:datetime"},
    # {"type": "openrouter:web_search"},
    # {"type": "openrouter:web_fetch"},
]

# Keywords that trigger fusion (multi-model deliberation)
_DEEP_ANALYSIS_KEYWORDS = [
    "arquitetura", "arquitectura", "architecture",
    "compara", "compare", "versus", "vs",
    "prós e contras", "pros and cons", "tradeoff",
    "analise", "analisa", "analyse", "analyze",
    "design review", "code review",
    "debug", "debugging", "root cause",
    "melhor prática", "best practice",
    "qual é a melhor", "which is better",
    "dilema", "dilemma",
    "pesquisa", "research",
]


def _is_deep_analysis(prompt: str) -> bool:
    """Heurística simples para detectar pedidos de análise profunda."""
    lower = prompt.lower()
    return any(kw in lower for kw in _DEEP_ANALYSIS_KEYWORDS)


def _build_tools(
    user_tools: list[dict[str, Any]] | None = None,
    *,
    tier: str | None = None,
    prompt: str = "",
) -> list[dict[str, Any]]:
    """Constrói o array de tools: defaults + tier-specific + fusion."""
    all_tools: list[dict[str, Any]] = list(DEFAULT_OPENROUTER_TOOLS)

    # Tier economy → advisor (modelo barato pede ajuda ao sénior)
    if tier == "economy":
        all_tools.append({"type": "openrouter:advisor"})

    # Deep analysis → fusion (painel multi-modelo)
    if _is_deep_analysis(prompt):
        all_tools.append({"type": "openrouter:fusion"})

    # User-provided tools (agent tools, function calling)
    if user_tools:
        all_tools.extend(user_tools)

    return all_tools


# ═══ Headers ═══


def _headers() -> dict[str, str]:
    key = (OPENROUTER_API_KEY or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not configured")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://central.nousresearch.com",
        "X-Title": "Central",
    }


# ═══ Direct LLM call ═══


def call_openrouter(
    prompt: str,
    *,
    model: str | None = None,
    models: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_format: dict[str, str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    tier: str | None = None,
    sort: str | None = None,
    order: list[str] | None = None,
    ignore: list[str] | None = None,
    allow_fallbacks: bool | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    """Single-turn inference via OpenRouter chat completions.

    Args:
        model: Single model ID (legacy, use models[] instead).
        models: Fallback chain — OpenRouter tries each in order on failure.
        sort: Provider routing — "price", "throughput", or "latency".
        order: Manual provider cascade — ["DeepSeek", "DeepInfra"].
        ignore: Provider blacklist — ["Baidu"].
        allow_fallbacks: If False, only uses providers in `order`.
        tool_choice: "auto" (default), "none", "required", or {"type":"function","function":{"name":"x"}}.
    """
    messages: list[dict[str, str]] = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    # ── Build body ──
    body: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "transforms": ["middle-out"],
    }

    # Model selection: models[] (fallback chain) takes priority over model
    if models:
        body["models"] = models
    elif model:
        body["model"] = model
    else:
        body["model"] = "openai/gpt-4o-mini"

    if response_format:
        body["response_format"] = response_format
    body["tools"] = _build_tools(tools, tier=tier, prompt=prompt)
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    # Provider routing
    if sort:
        body["sort"] = sort
    if order:
        body["order"] = order
    if ignore:
        body["ignore"] = ignore
    if allow_fallbacks is not None:
        body["allow_fallbacks"] = allow_fallbacks
    if effort:
        body["reasoning"] = {"effort": effort}

    t0 = time.monotonic()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(OPENROUTER_CHAT_URL, json=body, headers=_headers())
        r.raise_for_status()
        data = r.json()

    elapsed = time.monotonic() - t0
    choice = data.get("choices", [{}])[0]
    usage = data.get("usage", {})

    return {
        "reply": choice.get("message", {}).get("content", ""),
        "model": data.get("model", model or (models[0] if models else "unknown")),
        "provider": data.get("provider", ""),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "elapsed_sec": round(elapsed, 2),
        "tool_calls": choice.get("message", {}).get("tool_calls"),
    }


def call_openrouter_stream(
    prompt: str,
    *,
    model: str | None = None,
    models: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    tier: str | None = None,
    sort: str | None = None,
    order: list[str] | None = None,
    ignore: list[str] | None = None,
    allow_fallbacks: bool | None = None,
    effort: str | None = None,
) -> Iterator[str]:
    """Streaming inference via OpenRouter. Yields NDJSON lines.

    Event types:
        {"e":"token","d":"..."}      — text chunk
        {"e":"tool_calls","d":[...]}  — tool call delta
        {"e":"provider","d":"..."}    — provider name (transparency)
        {"e":"usage","d":{...}}       — token usage snapshot
        {"e":"done","reply":"..."}    — end of stream
    """
    messages: list[dict[str, str]] = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
        "transforms": ["middle-out"],
    }

    if models:
        body["models"] = models
    elif model:
        body["model"] = model
    else:
        body["model"] = "openai/gpt-4o-mini"

    body["tools"] = _build_tools(tools, tier=tier, prompt=prompt)
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    if sort:
        body["sort"] = sort
    if order:
        body["order"] = order
    if ignore:
        body["ignore"] = ignore
    if allow_fallbacks is not None:
        body["allow_fallbacks"] = allow_fallbacks
    if effort:
        body["reasoning"] = {"effort": effort}

    accumulated = ""
    last_provider = ""
    last_usage: dict[str, Any] | None = None

    # Retry on transient errors (rate limiting, gateway timeouts)
    import time as _time
    max_attempts = 3
    base_delay = 2.0
    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=300.0) as client:
                with client.stream("POST", OPENROUTER_CHAT_URL, json=body, headers=_headers()) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line or not line.strip():
                            continue
                        if line.startswith("data: "):
                            chunk = line[6:]
                            if chunk.strip() == "[DONE]":
                                if last_usage:
                                    yield json.dumps({"e": "usage", "d": last_usage}) + "\n"
                                yield json.dumps({"e": "done", "reply": accumulated}) + "\n"
                                return
                            try:
                                data = json.loads(chunk)

                                # ── Provider transparency ──
                                provider = data.get("provider") or data.get("provider_name")
                                if provider and provider != last_provider:
                                    last_provider = str(provider)
                                    yield json.dumps({"e": "provider", "d": last_provider}) + "\n"

                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                tool_calls = delta.get("tool_calls")

                                if tool_calls:
                                    yield json.dumps({"e": "tool_calls", "d": tool_calls}) + "\n"
                                if content:
                                    accumulated += content
                                    yield json.dumps({"e": "token", "d": content}) + "\n"

                                # ── Usage tracking ──
                                if data.get("usage"):
                                    last_usage = data["usage"]
                                    yield json.dumps({"e": "usage", "d": last_usage}) + "\n"
                            except json.JSONDecodeError:
                                continue
                    # If stream ended without [DONE], yield what we have
                    if accumulated:
                        if last_usage:
                            yield json.dumps({"e": "usage", "d": last_usage}) + "\n"
                        yield json.dumps({"e": "done", "reply": accumulated}) + "\n"
                    return
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code in (429, 502, 503, 504) and attempt + 1 < max_attempts:
                delay = base_delay * (2 ** attempt)
                _time.sleep(delay)
                continue
            raise
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
            if attempt + 1 < max_attempts:
                delay = base_delay * (2 ** attempt)
                _time.sleep(delay)
                continue
            raise


def call_openrouter_raw(
    raw_messages: list[dict[str, Any]],
    *,
    model: str = "openai/gpt-4o",
    models: list[str] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_format: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Multimodal inference via OpenRouter chat completions.

    raw_messages deve seguir o formato OpenAI:
        [{"role": "user", "content": [{"type": "text", "text": "..."}, ...]}]
    """
    body: dict[str, Any] = {
        "messages": raw_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "transforms": ["middle-out"],
    }

    if models:
        body["models"] = models
    else:
        body["model"] = model

    if response_format:
        body["response_format"] = response_format
    body["tools"] = DEFAULT_OPENROUTER_TOOLS

    t0 = time.monotonic()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(OPENROUTER_CHAT_URL, json=body, headers=_headers())
        r.raise_for_status()
        data = r.json()

    elapsed = time.monotonic() - t0
    choice = data.get("choices", [{}])[0]
    usage = data.get("usage", {})

    return {
        "reply": choice.get("message", {}).get("content", ""),
        "model": data.get("model", model),
        "provider": data.get("provider", ""),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "elapsed_sec": round(elapsed, 2),
    }
