import logging
from collections.abc import Iterator
from typing import Any

import httpx

from app.inference import (
    AllowlistMode,
    validate_modality_model_router_override,
    validate_outbound_model_router_override,
    validate_ui_model_router_override,
)
from app.shared.l8_pipeline_policy import transport_retry_config
from app.inference import backoff_sleep, execute_with_http_retries
from app.config import (
    DISABLE_STT,
    DISABLE_TTS,
    KERNEL_OBSERVER_URL,
    LLM_SERVICE_URL,
    LLM_USAGE_METRICS_ENABLED,
    MODEL_ROUTER_URL,
    OPENROUTER_API_KEY,
    ORCHESTRATOR_TIMEOUT_SECONDS,
    STT_SERVICE_URL,
    SYSTEM_AGENT_URL,
    TTS_SERVICE_URL,
)
from app.shared.openrouter_audio import (
    legacy_stt_configured,
    legacy_tts_configured,
    openrouter_stt_configured,
    openrouter_tts_configured,
    synthesize_speech_openrouter,
    transcribe_audio_bytes,
)

logger = logging.getLogger(__name__)


def call_model_router_raw_messages(
    raw_messages: list[dict[str, Any]],
    *,
    profile: str = "balanced",
    response_format: dict[str, str] | None = None,
    model_override: str | None = None,
    allowlist_mode: AllowlistMode = "ui",
) -> str:
    """POST /infer com raw_messages (multimodal OpenAI)."""
    # ── Direct OpenRouter path (T11) ──
    if not (MODEL_ROUTER_URL or "").strip():
        from app.shared.openrouter_client import call_openrouter_raw

        result = call_openrouter_raw(
            raw_messages,
            model=model_override or "openai/gpt-4o",
            response_format=response_format,
        )
        return str(result.get("reply", "")).strip()

    # ── Legacy model-router path ──
    if allowlist_mode == "modality":
        validate_modality_model_router_override(model_override)
    else:
        validate_ui_model_router_override(model_override)
    payload: dict[str, Any] = {"raw_messages": raw_messages, "profile": profile}
    if response_format is not None:
        payload["response_format"] = response_format
    if model_override:
        payload["model_override"] = model_override
    cfg = transport_retry_config()
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:

        def _do() -> httpx.Response:
            r = client.post(f"{MODEL_ROUTER_URL.rstrip('/')}/infer", json=payload)
            r.raise_for_status()
            return r

        response = execute_with_http_retries(
            _do,
            max_attempts=int(cfg["max_attempts"]),
            retry_statuses=set(cfg["retry_on_status"]),
            base_delay_ms=int(cfg["base_delay_ms"]),
            max_delay_ms=int(cfg["max_delay_ms"]),
            jitter_ratio=float(cfg["jitter_ratio"]),
        )
        data = response.json()
    if LLM_USAGE_METRICS_ENABLED and isinstance(data, dict):
        from app.tools import record_llm_usage_from_payload
        record_llm_usage_from_payload(profile, data)
    return str(data.get("reply", "")).strip()


def call_llm(
    message: str,
    history: list[dict[str, str]] | None = None,
    *,
    profile: str = "balanced",
    response_format: dict[str, str] | None = None,
    model_override: str | None = None,
    allowlist_mode: AllowlistMode = "ui",
    tools: list[dict[str, Any]] | None = None,
) -> str:
    # Quota check before inference
    from app.tenant_quota import check_quota as _check_quota, increment_usage as _increment_usage
    from app.shared.pg_tenant import resolve_pg_tenant_id

    tid = resolve_pg_tenant_id()
    allowed, err = _check_quota(tid)
    if not allowed:
        raise RuntimeError(err or "quota_exceeded")

    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        if MODEL_ROUTER_URL:
            if allowlist_mode == "modality":
                validate_modality_model_router_override(model_override)
            else:
                validate_ui_model_router_override(model_override)
            payload: dict[str, Any] = {"text": message, "history": history or [], "profile": profile}
            if response_format is not None:
                payload["response_format"] = response_format
            if model_override:
                payload["model_override"] = model_override
            cfg = transport_retry_config()

            def _do() -> httpx.Response:
                r = client.post(f"{MODEL_ROUTER_URL.rstrip('/')}/infer", json=payload)
                r.raise_for_status()
                return r

            # T6: circuit breaker wrapping the retry loop
            from app.shared.openrouter_resilience import call_with_circuit_breaker

            response = call_with_circuit_breaker(
                lambda: execute_with_http_retries(
                _do,
                max_attempts=int(cfg["max_attempts"]),
                retry_statuses=set(cfg["retry_on_status"]),
                base_delay_ms=int(cfg["base_delay_ms"]),
                max_delay_ms=int(cfg["max_delay_ms"]),
                jitter_ratio=float(cfg["jitter_ratio"]),
            )
            )
            data = response.json()
        else:
            # ── OpenRouter direct path (T11) ──
            from app.shared.openrouter_client import call_openrouter
            from app.shared.openrouter_resilience import call_with_circuit_breaker

            model_id = model_override or "openai/gpt-4o-mini"

            # ── Tier profile: models[] (fallback chain) ──
            tier_routing: dict[str, Any] = {}
            tier = "balanced"  # default
            try:
                from app.user_config import get_user_tier_profile, get_user_provider_routing
                from app.inference import _resolve_current_user_id

                uid = _resolve_current_user_id()
                if uid:
                    # Provider routing (user preference — cheapest/fastest/throughput)
                    routing = get_user_provider_routing(uid)
                    if routing.get("sort"):
                        tier_routing["sort"] = routing["sort"]
                    if routing.get("order"):
                        tier_routing["order"] = routing["order"]
                # Fallback: provider_routing from assistant_preferences.json
                if not tier_routing.get("sort") and not tier_routing.get("order"):
                    from app.shared.assistant_preferences import load_preferences
                    pr = str(load_preferences().get("provider_routing") or "").strip()
                    if pr == "cheapest":
                        tier_routing["sort"] = "price"
                        tier_routing["order"] = "asc"
                    elif pr == "fastest":
                        tier_routing["sort"] = "latency"
                        tier_routing["order"] = "asc"
                    elif pr == "throughput":
                        tier_routing["sort"] = "throughput"
                        tier_routing["order"] = "desc"

                    # Tier profile: models[] (fallback chain)
                    tier_map = {"eco": "economy", "balanced": "balanced", "quality": "premium"}
                    tier = tier_map.get(profile, "balanced")
                    tp = get_user_tier_profile(uid, tier)
                    if tp and tp.get("models"):
                        tier_routing["models"] = tp["models"]
            except Exception:
                pass

            def _do_openrouter() -> dict[str, Any]:
                from app.shared.assistant_preferences import load_preferences
                prefs = load_preferences()
                temp = float(prefs.get("temperature") or 0.7)
                if temp <= 0.0:
                    temp = 0.7
                kwargs: dict[str, Any] = {
                    "prompt": message,
                    "history": history,
                    "temperature": temp,
                    "response_format": response_format,
                    "tier": tier,  # para advisor/fusion tools
                }
                if prefs.get("effort"):
                    kwargs["effort"] = prefs["effort"]
                # Use models[] from tier profile, or single model as fallback
                if tier_routing.get("models"):
                    kwargs["models"] = tier_routing["models"]
                else:
                    kwargs["model"] = model_id
                if tier_routing.get("sort"):
                    kwargs["sort"] = tier_routing["sort"]
                if tier_routing.get("order"):
                    kwargs["order"] = tier_routing["order"]
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                return call_openrouter(**kwargs)

            data = call_with_circuit_breaker(_do_openrouter)
    # ── Usage tracking (model-router or direct) ──
    if LLM_USAGE_METRICS_ENABLED and isinstance(data, dict):
        from app.tools import record_llm_usage_from_payload
        if MODEL_ROUTER_URL:
            record_llm_usage_from_payload(profile, data)
        # Quota increment from usage data
        usage = data.get("usage")
        if isinstance(usage, dict):
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            if pt > 0 or ct > 0:
                try:
                    _increment_usage(tid, tokens_input=pt, tokens_output=ct)
                except Exception:
                    pass
    return str(data.get("reply", "")).strip()


def iter_assistant_llm_ndjson(
    message: str,
    history: list[dict[str, str]] | None = None,
    *,
    profile: str = "balanced",
    response_format: dict[str, str] | None = None,
    model_override: str | None = None,
) -> Iterator[str]:
    """
    Linhas NDJSON do LLM ou model-router (/chat/stream ou /infer/stream).
    Cada linha: {"e":"token","d":"..."} | {"e":"done"} | {"e":"error","message":"..."}
    """
    hist = history or []
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        if MODEL_ROUTER_URL:
            validate_ui_model_router_override(model_override)
            url = f"{MODEL_ROUTER_URL.rstrip('/')}/infer/stream"
            body: dict = {"text": message, "history": hist, "profile": profile}
            if response_format is not None:
                body["response_format"] = response_format
            if model_override:
                body["model_override"] = model_override
            cfg = transport_retry_config()
            for attempt in range(int(cfg["max_attempts"])):
                try:
                    with client.stream("POST", url, json=body) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if line and line.strip():
                                yield line
                    return
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code if exc.response is not None else 0
                    if (
                        code in cfg["retry_on_status"]
                        and attempt + 1 < int(cfg["max_attempts"])
                    ):
                        backoff_sleep(
                            attempt,
                            int(cfg["base_delay_ms"]),
                            int(cfg["max_delay_ms"]),
                            float(cfg["jitter_ratio"]),
                        )
                        continue
                    raise
                except httpx.RequestError:
                    if attempt + 1 < int(cfg["max_attempts"]):
                        backoff_sleep(
                            attempt,
                            int(cfg["base_delay_ms"]),
                            int(cfg["max_delay_ms"]),
                            float(cfg["jitter_ratio"]),
                        )
                        continue
                    raise
        else:
            # ── OpenRouter direct streaming (T11) ──
            from app.shared.openrouter_client import call_openrouter_stream

            model_id = model_override or "openai/gpt-4o-mini"
            from app.shared.assistant_preferences import load_preferences
            prefs = load_preferences()
            temp = float(prefs.get("temperature") or 0.7)
            if temp <= 0.0:
                temp = 0.7
            stream_kwargs: dict[str, Any] = {
                "model": model_id,
                "history": hist,
                "temperature": temp,
            }
            if prefs.get("effort"):
                stream_kwargs["effort"] = prefs["effort"]

            # ── Tier profile: models[] + provider routing ──
            try:
                from app.user_config import get_user_tier_profile, get_user_provider_routing
                from app.inference import _resolve_current_user_id

                uid = _resolve_current_user_id()
                if uid:
                    # Provider routing
                    routing = get_user_provider_routing(uid)
                    if routing.get("sort"):
                        stream_kwargs["sort"] = routing["sort"]
                    if routing.get("order"):
                        stream_kwargs["order"] = routing["order"]
                # Fallback: provider_routing from assistant_preferences.json
                if not stream_kwargs.get("sort") and not stream_kwargs.get("order"):
                    pr = str(prefs.get("provider_routing") or "").strip()
                    if pr == "cheapest":
                        stream_kwargs["sort"] = "price"
                        stream_kwargs["order"] = "asc"
                    elif pr == "fastest":
                        stream_kwargs["sort"] = "latency"
                        stream_kwargs["order"] = "asc"
                    elif pr == "throughput":
                        stream_kwargs["sort"] = "throughput"
                        stream_kwargs["order"] = "desc"

                    # Tier models
                    tier_map = {"eco": "economy", "balanced": "balanced", "quality": "premium"}
                    tier = tier_map.get(profile, "balanced")
                    tp = get_user_tier_profile(uid, tier)
                    if tp and tp.get("models"):
                        stream_kwargs["models"] = tp["models"]
                        stream_kwargs.pop("model", None)
            except Exception:
                pass

            for ndjson_line in call_openrouter_stream(
                message,
                **stream_kwargs,
            ):
                yield ndjson_line


def call_tts(text: str, filename: str | None = None) -> str:
    if DISABLE_TTS:
        return ""
    if openrouter_tts_configured():
        try:
            return synthesize_speech_openrouter(text, filename=filename)
        except Exception as exc:
            logger.warning("openrouter_tts_failed: %s", exc)
            if not legacy_tts_configured():
                raise
    elif legacy_tts_configured():
        logger.warning(
            "tts_legacy_microservice: set CENTRAL_TTS_MODEL_ID + OPENROUTER_API_KEY (ADR-016)"
        )
    else:
        return ""
    payload = {"text": text}
    if filename:
        payload["filename"] = filename
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{TTS_SERVICE_URL}/synthesize", json=payload)
        response.raise_for_status()
        data = response.json()
    return str(data.get("audio_file", "")).strip()


def call_stt(file_bytes: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> str:
    if DISABLE_STT:
        raise RuntimeError("stt_disabled")
    if openrouter_stt_configured():
        try:
            return transcribe_audio_bytes(file_bytes, content_type=content_type or "audio/wav")
        except Exception as exc:
            logger.warning("openrouter_stt_failed: %s", exc)
            if not legacy_stt_configured():
                raise
    elif legacy_stt_configured():
        logger.warning(
            "stt_legacy_microservice: prefer MODEL_ROUTER_URL + audio_perceive (ADR-016)"
        )
    else:
        raise RuntimeError("stt_disabled")
    files = {"file": (filename, file_bytes, content_type)}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{STT_SERVICE_URL}/transcribe", files=files)
        response.raise_for_status()
        data = response.json()
    return str(data.get("text", "")).strip()


def call_system_agent_summary(request_id: str) -> dict:
    payload = {"request_id": request_id}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/system.summary", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_disk_usage(request_id: str) -> dict:
    """P0: uso de disco por mounts allowlist no system-agent."""
    payload = {"request_id": request_id}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/filesystem.disk.usage", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_workspace_grep(
    request_id: str,
    *,
    path: str,
    pattern: str,
    max_matches: int = 80,
) -> dict:
    """OC-10: ripgrep read-only (filesystem.workspace.grep)."""
    cap = max(1, min(500, int(max_matches)))
    payload = {
        "request_id": request_id,
        "path": path.strip(),
        "pattern": pattern.strip(),
        "max_matches": cap,
    }
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.workspace.grep",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_disk_partitions(request_id: str, *, limit: int = 64) -> dict:
    """P0-13: partições read-only (psutil.disk_partitions) no system-agent."""
    cap = max(1, min(128, int(limit)))
    payload = {"request_id": request_id, "limit": cap}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.disk.partitions",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_units_list(request_id: str, *, limit: int = 80) -> dict:
    """P0-6: lista read-only de unidades systemd tipo service (truncada no agente)."""
    cap = max(1, min(200, int(limit)))
    payload = {"request_id": request_id, "limit": cap}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/systemd.units.list",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_journal_tail(
    request_id: str,
    *,
    unit: str | None = None,
    identifier: str | None = None,
    since: str = "1h",
    max_bytes: int = 16384,
) -> dict:
    """P0-8: journalctl read-only (allowlist no system-agent)."""
    payload: dict = {
        "request_id": request_id,
        "since": since,
        "max_bytes": max(256, min(65536, int(max_bytes))),
    }
    if unit:
        payload["unit"] = unit
    if identifier:
        payload["identifier"] = identifier
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/systemd.journal.tail",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_packages_query(request_id: str, *, package: str) -> dict:
    """P0-9: rpm/dpkg-query read-only com allowlist no system-agent."""
    payload = {"request_id": request_id, "package": package.strip()}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/os.packages.query",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_process_list(request_id: str) -> dict:
    """P0: lista de processos via system-agent (policy allowlist)."""
    payload = {"request_id": request_id}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/process.list", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_process_tree(
    request_id: str,
    *,
    limit: int = 80,
    max_depth: int = 12,
) -> dict:
    """P0-7: processos com PPID e profundidade (read-only, truncado no agente)."""
    cap = max(1, min(200, int(limit)))
    depth = max(1, min(32, int(max_depth)))
    payload = {"request_id": request_id, "limit": cap, "max_depth": depth}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/process.tree",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_filesystem_path_stat(request_id: str, *, rel_path: str) -> dict:
    """P0: stat metadata sob CENTRAL_ROOT (sem conteudo)."""
    payload = {"request_id": request_id, "path": rel_path}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.path.stat",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_filesystem_path_read(
    request_id: str,
    *,
    rel_path: str,
    max_bytes: int = 32768,
) -> dict:
    """P0-11: leitura texto UTF-8 sob CENTRAL_ROOT (allowlist no agente)."""
    cap = max(256, min(65536, int(max_bytes)))
    payload = {"request_id": request_id, "path": rel_path, "max_bytes": cap}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.path.read",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_hardware_sensors(request_id: str) -> dict:
    """P0-12: sensores hardware read-only (best-effort no system-agent)."""
    payload = {"request_id": request_id}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/hardware.sensors",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_network_interfaces(request_id: str) -> dict:
    """P0 Onda 2: interfaces e endereços (read-only)."""
    payload = {"request_id": request_id}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.interfaces",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_network_routes(request_id: str, *, limit: int = 32) -> dict:
    """P0 Onda 2: rotas IPv4 (Linux /proc/net/route), truncado."""
    cap = max(1, min(100, int(limit)))
    payload = {"request_id": request_id, "limit": cap}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.routes",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_network_connections(
    request_id: str,
    *,
    limit: int = 100,
    state: str = "ESTABLISHED",
) -> dict:
    """P0 Onda 2: conexões inet (resumo, truncado)."""
    cap = max(1, min(500, int(limit)))
    st = (state or "ESTABLISHED").strip().upper()
    payload = {"request_id": request_id, "limit": cap, "state": st}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.connections",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_network_listen_sockets(request_id: str, *, limit: int = 200) -> dict:
    """K.1 P0: sockets inet em escuta (sem raddr)."""
    cap = max(1, min(500, int(limit)))
    payload = {"request_id": request_id, "limit": cap}
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.listen.sockets",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_unit_restart(
    request_id: str,
    unit: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    payload = {
        "request_id": request_id,
        "unit": unit,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    # pkexec pode esperar autenticacao humana
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/systemd.unit.restart", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_unit_stop(
    request_id: str,
    unit: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    payload = {
        "request_id": request_id,
        "unit": unit,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/systemd.unit.stop", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_user_unit_disable(
    request_id: str,
    unit: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P2 Onda 2: systemctl --user disable (.timer / .socket)."""
    payload = {
        "request_id": request_id,
        "unit": unit,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 120.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/systemd.user.unit.disable",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_os_power_reboot(
    request_id: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 2: systemctl reboot via system-agent + pkexec (apos approval + K.2)."""
    payload = {
        "request_id": request_id,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/os.power.reboot", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_os_power_shutdown(
    request_id: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 2: systemctl poweroff via system-agent + pkexec (apos approval + K.2)."""
    payload = {
        "request_id": request_id,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/os.power.shutdown", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_unit_enable(
    request_id: str,
    unit: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 3: systemctl enable (system scope)."""
    payload = {
        "request_id": request_id,
        "unit": unit,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/systemd.unit.enable", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_os_account_unix_useradd(
    request_id: str,
    username: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 6a: useradd conta de sistema (Polkit + allowlist no host)."""
    payload = {
        "request_id": request_id,
        "username": username,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/os.account.unix_useradd", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_systemd_unit_disable_system(
    request_id: str,
    unit: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 3: systemctl disable (system scope); distinto de systemd.user.unit.disable."""
    payload = {
        "request_id": request_id,
        "unit": unit,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/systemd.unit.disable", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_process_signal(
    request_id: str,
    pid: int,
    signal_num: int,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    payload = {
        "request_id": request_id,
        "pid": pid,
        "signal": signal_num,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(f"{SYSTEM_AGENT_URL}/capabilities/process.signal", json=payload)
        response.raise_for_status()
        return response.json()


def call_system_agent_read_external_file(
    request_id: str,
    abs_path: str,
    approval_id: str,
    *,
    max_bytes: int = 16384,
    double_confirmation_ack: bool = False,
) -> dict:
    """P1-3: leitura texto apos aprovacao; allowlist absoluta no system-agent."""
    cap = max(256, min(65536, int(max_bytes)))
    payload = {
        "request_id": request_id,
        "path": abs_path,
        "max_bytes": cap,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.path.read_external",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_write_config_file(
    request_id: str,
    abs_path: str,
    content: str,
    approval_id: str,
    *,
    create_backup: bool = True,
    double_confirmation_ack: bool = False,
) -> dict:
    """P2-3: gravar texto apos aprovacao; allowlist no system-agent."""
    payload = {
        "request_id": request_id,
        "path": abs_path,
        "content": content,
        "create_backup": create_backup,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.path.write_config",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_mutate_external_path(
    request_id: str,
    operation: str,
    src_path: str,
    approval_id: str,
    *,
    dst_path: str | None = None,
    double_confirmation_ack: bool = False,
) -> dict:
    """P2-6: copy/move/delete ficheiro regular apos aprovacao; allowlists no system-agent."""
    payload: dict = {
        "request_id": request_id,
        "operation": operation,
        "src_path": src_path,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    if dst_path is not None and str(dst_path).strip():
        payload["dst_path"] = str(dst_path).strip()
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/filesystem.path.mutate_external",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_firewall_policy_apply(
    request_id: str,
    operation: str,
    approval_id: str,
    *,
    zone: str | None = None,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3 Onda 5: reload firewalld ou set-default-zone apos aprovacao (K.2 quando policy exige)."""
    payload: dict = {
        "request_id": request_id,
        "approval_id": approval_id,
        "operation": operation,
        "double_confirmation_ack": double_confirmation_ack,
    }
    if zone is not None and str(zone).strip():
        payload["zone"] = str(zone).strip()
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.firewall.policy.apply",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_firewall_rule_apply(
    request_id: str,
    port: int,
    protocol: str,
    direction: str,
    rule_action: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P2-4: aplicar regra pontual apos aprovacao; backend e allowlist no system-agent."""
    payload = {
        "request_id": request_id,
        "port": port,
        "protocol": protocol,
        "direction": direction,
        "action": rule_action,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 300.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/network.firewall.rule.apply",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_os_packages_install(
    request_id: str,
    package: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P2-5: instalar pacote allowlisted apos aprovacao (pkexec + helper no system-agent)."""
    payload = {
        "request_id": request_id,
        "package": package.strip(),
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 660.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/os.packages.install",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_system_agent_os_packages_upgrade_all(
    request_id: str,
    approval_id: str,
    *,
    double_confirmation_ack: bool = False,
) -> dict:
    """P3-4: upgrade massivo apos aprovacao (pkexec + helper; opt-in no system-agent)."""
    payload = {
        "request_id": request_id,
        "approval_id": approval_id,
        "double_confirmation_ack": double_confirmation_ack,
    }
    timeout = max(ORCHESTRATOR_TIMEOUT_SECONDS, 7200.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{SYSTEM_AGENT_URL}/capabilities/os.packages.upgrade_all",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def call_kernel_observer_snapshot(request_id: str) -> dict:
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{KERNEL_OBSERVER_URL}/snapshot",
            headers={"X-Request-Id": request_id},
        )
        response.raise_for_status()
        return response.json()


def call_kernel_observer_audit_summary(request_id: str) -> dict:
    """Fase E / K.5: amostra auditd com o mesmo request_id (header X-Request-Id)."""
    with httpx.Client(timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{KERNEL_OBSERVER_URL}/audit/summary",
            headers={"X-Request-Id": request_id},
        )
        response.raise_for_status()
        return response.json()


def fetch_host_summary_best_effort(request_id: str) -> dict:
    """
    Agregado read-only system-agent + kernel-observer; erros embutidos (sem excecao).
    Usado por pos-injecao e pela tool P0 get_host_summary (Fase F).
    """
    try:
        system_agent = call_system_agent_summary(request_id)
    except httpx.HTTPError as exc:
        system_agent = {"error": str(exc)}
    kernel_observer: dict | None = None
    kernel_observer_error: str | None = None
    try:
        kernel_observer = call_kernel_observer_snapshot(request_id)
    except httpx.HTTPError as exc:
        kernel_observer_error = str(exc)
    kernel_audit: dict | None = None
    kernel_audit_error: str | None = None
    try:
        kernel_audit = call_kernel_observer_audit_summary(request_id)
    except httpx.HTTPError as exc:
        kernel_audit_error = str(exc)
    return {
        "request_id": request_id,
        "system_agent": system_agent,
        "kernel_observer": kernel_observer,
        "kernel_observer_error": kernel_observer_error,
        "kernel_audit": kernel_audit,
        "kernel_audit_error": kernel_audit_error,
    }


def fetch_process_tree_for_tool(request_id: str, *, limit: int, max_depth: int) -> dict:
    """Árvore P0 (flat com depth); erros embutidos."""
    cap = max(1, min(200, int(limit)))
    depth = max(1, min(32, int(max_depth)))
    try:
        raw = call_system_agent_process_tree(request_id, limit=cap, max_depth=depth)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_processes_collected": 0,
            "total_after_depth_filter": 0,
            "truncated": False,
            "limit_applied": cap,
            "max_depth_applied": depth,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_process_list_for_tool(request_id: str, *, limit: int) -> dict:
    """
    Lista P0 truncada para o registry (evita prompts gigantes).
    limit clampado a [1, 200] pelo chamador apos schema.
    """
    cap = max(1, min(200, int(limit)))
    try:
        raw = call_system_agent_process_list(request_id)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_processes_reported": 0,
            "truncated": False,
            "limit_applied": cap,
        }
    items = raw.get("items")
    if not isinstance(items, list):
        items = []
    total = len(items)
    trimmed = items[:cap]
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        "total_processes_reported": total,
        "items": trimmed,
        "truncated": total > len(trimmed),
        "limit_applied": cap,
    }


def fetch_file_metadata_for_tool(request_id: str, *, rel_path: str) -> dict:
    """Stat P0; erros embutidos."""
    try:
        raw = call_system_agent_filesystem_path_stat(request_id, rel_path=rel_path)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "path": rel_path,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_read_file_text_for_tool(
    request_id: str,
    *,
    rel_path: str,
    max_bytes: int = 32768,
) -> dict:
    """Leitura texto P0-11; erros embutidos."""
    try:
        raw = call_system_agent_filesystem_path_read(
            request_id,
            rel_path=rel_path,
            max_bytes=max_bytes,
        )
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "path": rel_path,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_hardware_sensors_for_tool(request_id: str) -> dict:
    """P0-12 hardware best-effort; erros HTTP embutidos."""
    try:
        raw = call_system_agent_hardware_sensors(request_id)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "gpu_nvidia": {"status": "unavailable", "reason": "http_error"},
            "battery": {"status": "unavailable", "reason": "http_error"},
            "temperatures": {"status": "unavailable", "reason": "http_error"},
            "fans": {"status": "unavailable", "reason": "http_error"},
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_disk_usage_for_tool(request_id: str) -> dict:
    """Lista P0 de uso de disco; erros embutidos."""
    try:
        raw = call_system_agent_disk_usage(request_id)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_workspace_grep_for_tool(
    request_id: str,
    *,
    path: str,
    pattern: str,
    max_matches: int = 80,
) -> dict:
    """grep_workspace — erros HTTP embutidos."""
    try:
        raw = call_system_agent_workspace_grep(
            request_id,
            path=path,
            pattern=pattern,
            max_matches=max_matches,
        )
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "ok": False,
            "error": str(exc),
            "matches": [],
            "match_count": 0,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_disk_partitions_for_tool(request_id: str, *, limit: int) -> dict:
    """P0-13: partições/mountpoints read-only; erros embutidos."""
    cap = max(1, min(128, int(limit)))
    try:
        raw = call_system_agent_disk_partitions(request_id, limit=cap)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "truncated": False,
            "total_seen": 0,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_systemd_units_for_tool(request_id: str, *, limit: int) -> dict:
    """Lista P0 systemctl list-units (serviços); erros embutidos."""
    cap = max(1, min(200, int(limit)))
    try:
        raw = call_system_agent_systemd_units_list(request_id, limit=cap)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_units_reported": 0,
            "truncated": False,
            "limit_applied": cap,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_journal_tail_for_tool(
    request_id: str,
    *,
    unit: str | None,
    identifier: str | None,
    since: str,
    max_bytes: int,
) -> dict:
    """P0-8 journal; erros embutidos."""
    since_ok = since if since in ("5m", "15m", "1h", "6h", "24h", "today") else "1h"
    cap = max(256, min(65536, int(max_bytes)))
    try:
        raw = call_system_agent_journal_tail(
            request_id,
            unit=unit,
            identifier=identifier,
            since=since_ok,
            max_bytes=cap,
        )
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "text": "",
            "bytes_returned": 0,
            "truncated": False,
            "since_applied": since_ok,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_packages_query_for_tool(request_id: str, *, package: str) -> dict:
    """P0-9 pacotes; erros embutidos."""
    try:
        raw = call_system_agent_packages_query(request_id, package=package)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "lines": [],
            "package": package.strip(),
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_network_interfaces_for_tool(request_id: str) -> dict:
    """Interfaces P0; erros embutidos."""
    try:
        raw = call_system_agent_network_interfaces(request_id)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_interfaces": 0,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_network_routes_for_tool(request_id: str, *, limit: int) -> dict:
    """Rotas P0; erros embutidos."""
    cap = max(1, min(100, int(limit)))
    try:
        raw = call_system_agent_network_routes(request_id, limit=cap)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_routes": 0,
            "truncated": False,
            "limit_applied": cap,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_network_connections_for_tool(
    request_id: str,
    *,
    limit: int,
    state: str = "ESTABLISHED",
) -> dict:
    """Conexões P0; erros embutidos."""
    cap = max(1, min(500, int(limit)))
    st = (state or "ESTABLISHED").strip().upper()
    if st not in ("ESTABLISHED", "ALL_ACTIVE"):
        st = "ESTABLISHED"
    try:
        raw = call_system_agent_network_connections(request_id, limit=cap, state=st)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_matched": 0,
            "truncated": False,
            "limit_applied": cap,
            "state_filter": st,
        }
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        **{k: v for k, v in raw.items() if k != "request_id"},
    }


def fetch_listening_sockets_for_tool(request_id: str, *, limit: int) -> dict:
    """Lista P0 de portas em escuta; erros embutidos (sem excepcao)."""
    cap = max(1, min(500, int(limit)))
    try:
        raw = call_system_agent_network_listen_sockets(request_id, limit=cap)
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "error": str(exc),
            "items": [],
            "total_listeners": 0,
            "truncated": False,
            "limit_applied": cap,
        }
    items = raw.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "request_id": request_id,
        "system_agent_request_id": raw.get("request_id"),
        "total_listeners": raw.get("total_listeners", len(items)),
        "truncated": bool(raw.get("truncated")),
        "limit_applied": raw.get("limit_applied", cap),
        "items": items,
        "error": raw.get("error"),
        "detail": raw.get("detail"),
    }
