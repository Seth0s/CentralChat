#!/usr/bin/env python3
"""T13 — Connector Inference Client: polls VPS for inference_ready, streams to OpenRouter.

Flow:
1. Connector registers with VPS (heartbeat)
2. VPS sends inference_ready message (prompt + model + config)
3. Connector calls OpenRouter directly, streams tokens to stdout/browser
4. Connector sends inference_complete back to VPS (usage + reply + errors)

Usage:
    python scripts/connector_inference.py --vps-url http://vps:8004 [--api-key sk-or-v1-...]
"""

import json
import os
import sys
import time
from typing import Any

import httpx

# ── Config ──
VPS_URL = os.getenv("CENTRAL_VPS_URL", "http://localhost:8004")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
CONNECTOR_ID = os.getenv("CENTRAL_CONNECTOR_ID", f"connector-{os.uname().nodename}")

for arg in sys.argv:
    if arg.startswith("--vps-url="):
        VPS_URL = arg.split("=", 1)[1]
    elif arg.startswith("--api-key="):
        OPENROUTER_KEY = arg.split("=", 1)[1]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }


def _register() -> None:
    """Register connector with VPS."""
    try:
        r = httpx.post(
            f"{VPS_URL.rstrip('/')}/connector/register",
            json={"connector_id": CONNECTOR_ID, "protocol_version": "1", "capabilities": ["inference", "shell"]},
            timeout=5.0,
        )
        print(f"[connector] Register: HTTP {r.status_code}", flush=True)
    except Exception as exc:
        print(f"[connector] Register failed: {exc}", flush=True)


def _report_complete(request_id: str, reply: str, model: str, usage: dict, error: str | None = None) -> None:
    """Send inference_complete back to VPS."""
    try:
        r = httpx.post(
            f"{VPS_URL.rstrip('/')}/connector/inference-complete",
            json={"request_id": request_id, "reply": reply, "model": model, "usage": usage, "error": error},
            timeout=5.0,
        )
        print(f"[connector] Complete reported: HTTP {r.status_code}", flush=True)
    except Exception as exc:
        print(f"[connector] Complete report failed: {exc}", flush=True)


def run_inference(inference: dict[str, Any]) -> dict[str, Any]:
    """Execute inference via OpenRouter, returning result."""
    prompt = inference.get("prompt", "")
    model = inference.get("model", "openai/gpt-4o-mini")
    history = inference.get("history", [])
    tools = inference.get("tools", [])
    max_tokens = inference.get("max_tokens", 4096)
    temperature = inference.get("temperature", 0.7)
    stream = inference.get("stream", True)

    messages = list(history) + [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": stream}
    if tools:
        body["tools"] = tools
    if stream:
        body["stream_options"] = {"include_usage": True}

    reply = ""
    usage = {}
    error = None

    try:
        if stream:
            with httpx.Client(timeout=300.0) as client:
                with client.stream("POST", OPENROUTER_URL, json=body, headers=_headers()) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line or not line.strip():
                            continue
                        if line.startswith("data: "):
                            chunk = line[6:]
                            if chunk.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(chunk)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    reply += content
                                    sys.stdout.write(content)
                                    sys.stdout.flush()
                                if data.get("usage"):
                                    usage = data["usage"]
                            except json.JSONDecodeError:
                                continue
        else:
            r = httpx.post(OPENROUTER_URL, json={**body, "stream": False}, headers=_headers(), timeout=120.0)
            r.raise_for_status()
            data = r.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
    except Exception as exc:
        error = str(exc)[:500]
        print(f"\n[connector] Error: {error}", flush=True)

    return {"reply": reply, "usage": usage, "error": error, "model": model}


# ── Main loop ──
_register()

print(f"[connector] Ready. VPS={VPS_URL} Connector={CONNECTOR_ID}", flush=True)
print(f"[connector] Paste inference_ready JSON to stdin, or pipe from VPS:", flush=True)
print(f'[connector]   curl -s {VPS_URL}/inference_ready | python3 connector_inference.py', flush=True)

# Read inference_ready from stdin (JSON, one per line)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue

    if msg.get("type") == "inference_ready":
        rid = msg.get("request_id", "unknown")
        print(f"\n[connector] Inference start: {rid}", flush=True)
        result = run_inference(msg)
        _report_complete(rid, result["reply"], result["model"], result["usage"], result["error"])
        print(f"\n[connector] Inference done: {rid}", flush=True)
