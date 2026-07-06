"""
P0-10: agregado read-only de health dos serviços conhecidos (URLs por env).
Só orquestrador — sem system-agent.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import (
    DISABLE_LLM_SERVICE,
    KERNEL_OBSERVER_URL,
    MEMORY_DB_URL,
    MEMORY_ENABLED,
    LLM_SERVICE_URL,
    MODEL_ROUTER_URL,
    OPENROUTER_API_KEY,
    PROMETHEUS_URL,
    STACK_HEALTH_PROBE_TIMEOUT,
    SYSTEM_AGENT_URL,
)
from app.shared.openrouter_audio import stack_health_stt_entry, stack_health_tts_entry


def _probe_health_url(base_url: str, paths: tuple[str, ...], timeout: float) -> dict[str, Any]:
    base = base_url.strip().rstrip("/")
    last: str | None = None
    for path in paths:
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{base}{path}")
            if 200 <= r.status_code < 300:
                return {"status": "ok", "http_status": r.status_code, "health_path": path}
            last = f"http_status_{r.status_code}"
        except httpx.HTTPError as exc:
            last = str(exc)
    return {"status": "error", "detail": last or "unreachable"}


def _entry(
    *,
    url: str,
    disabled: bool,
    paths: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    if disabled:
        return {"status": "disabled"}
    if not url or not url.strip():
        return {"status": "skipped", "detail": "not_configured"}
    row = _probe_health_url(url, paths, timeout)
    row["url"] = url.strip().rstrip("/")
    return row


def collect_central_stack_health(request_id: str) -> dict[str, Any]:
    """
    Devolve mapa por serviço + contagem por estado.
    Prometheus: `/-/healthy` primeiro (padrão Prometheus 2+).
    """
    timeout = max(0.5, min(30.0, STACK_HEALTH_PROBE_TIMEOUT))
    health_paths = ("/health",)
    prom_paths = ("/-/healthy", "/-/ready", "/health")

    services: dict[str, dict[str, Any]] = {}
    if MODEL_ROUTER_URL:
        services["model_router"] = _entry(
            url=MODEL_ROUTER_URL,
            disabled=False,
            paths=health_paths,
            timeout=timeout,
        )
    if OPENROUTER_API_KEY:
        services["openrouter_api"] = _entry(
            url="https://openrouter.ai/api/v1/models",
            disabled=False,
            paths=("/",),
            timeout=timeout,
        )
    services.update({
        "system_agent": _entry(
            url=SYSTEM_AGENT_URL,
            disabled=False,
            paths=health_paths,
            timeout=timeout,
        ),
        "kernel_observer": _entry(
            url=KERNEL_OBSERVER_URL,
            disabled=False,
            paths=health_paths,
            timeout=timeout,
        ),
        "stt": stack_health_stt_entry(),
        "llm": _entry(
            url=LLM_SERVICE_URL,
            disabled=DISABLE_LLM_SERVICE,
            paths=health_paths,
            timeout=timeout,
        ),
        "tts": stack_health_tts_entry(),
        "prometheus": _entry(
            url=PROMETHEUS_URL,
            disabled=False,
            paths=prom_paths,
            timeout=timeout,
        ),
        # Memória externa (Postgres): não é HTTP; reportamos apenas se está configurado.
        "memory_db": {"status": "ok" if (MEMORY_ENABLED and bool(MEMORY_DB_URL)) else "disabled"},
    })

    summary: dict[str, int] = {"ok": 0, "error": 0, "disabled": 0, "skipped": 0}
    for row in services.values():
        st = str(row.get("status") or "error")
        if st in summary:
            summary[st] += 1
        else:
            summary["error"] += 1

    return {
        "request_id": request_id,
        "services": services,
        "summary": summary,
        "probe_timeout_seconds": timeout,
    }
