"""T13 — Inference Ready payload builder (VPS side).

Builds the inference_ready message that the VPS sends to the connector.
Includes: prompt, model config, tools, history, and stream config.
"""

from __future__ import annotations

from typing import Any


def build_inference_ready(
    *,
    request_id: str,
    prompt: str,
    history: list[dict[str, str]] | None = None,
    model: str = "openai/gpt-4o-mini",
    profile: str = "balanced",
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    stream: bool = True,
    chat_session_id: str | None = None,
) -> dict[str, Any]:
    """
    Build the inference_ready payload sent from VPS to connector.

    The connector receives this and calls OpenRouter directly,
    streaming tokens to the browser.
    """
    return {
        "type": "inference_ready",
        "request_id": request_id,
        "model": model,
        "profile": profile,
        "prompt": prompt,
        "history": history or [],
        "tools": tools or [],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
        "chat_session_id": chat_session_id,
    }


def build_inference_complete(
    *,
    request_id: str,
    reply: str,
    model: str,
    usage: dict[str, int] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Build the inference_complete payload sent from connector back to VPS.
    The VPS persists session events and updates quota from this.
    """
    return {
        "type": "inference_complete",
        "request_id": request_id,
        "reply": reply,
        "model": model,
        "usage": usage or {},
        "error": error,
    }
