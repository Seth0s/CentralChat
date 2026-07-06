"""Central Orchestrator — thin router layer. Domain logic lives in domain files."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.shared.ambientacao import (
    build_capability_digest_pt_br,
    build_capability_digest_system_message,
    build_post_host_system_message,
    build_pre_injection_message,
    get_pre_injection_body,
    truncate_session_history,
)
from app.repositories.preferences_repository import (
    load_preferences,
    preferences_system_messages,
)
from app.clients import call_llm, call_stt, call_tts
from app.shared.host_context_trigger import should_inject_host_context_from_text
from app.shared.platform_context import include_platform_host_context
from app.inference import resolve_aux_llm_call_params
from app.actions import run_network_probe, validate_probe_for_queue
from app.shared.assistant_hybrid_pipeline import (
    iter_ndjson_lines_with_stream_fallback,
    record_pipeline_decision,
)
from app.config import (
    API_HOST,
    API_PORT,
    DISABLE_STT,
    DISABLE_TTS,
    DISABLE_LLM_SERVICE,
    CENTRAL_SESSION_RAG_ENABLED,
    AGENT_TOOLS_ENABLED,
    AGENT_TOOLS_FEW_SHOT_ENABLED,
    AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED,
    AGENT_TOOLS_JSON_MODE_ENABLED,
    AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS,
    AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS,
    AGENT_TOOLS_MAX_EXECUTIONS,
    CAPABILITY_DIGEST_IN_PROMPT_ENABLED,
    CENTRAL_FOCUS_MODE,
    CLOUD_ROUTER_PROFILE,
    COMPACT_AFTER_CHARS,
    COMPACT_AFTER_MESSAGES,
    COMPACT_KEEP_LAST_MESSAGES,
    COMPACT_SUMMARY_STORE_PATH,
    MEMORY_MAX_BLOCK_CHARS,
    MEMORY_TOP_K,
    KERNEL_OBSERVER_URL,
    LLM_SERVICE_URL,
    LLM_USAGE_METRICS_ENABLED,
    MODEL_ROUTER_URL,
    ORCHESTRATOR_TIMEOUT_SECONDS,
    PRE_INJECTION_ENABLED,
    PRE_INJECTION_FILE_PATH,
    SECRETS_VAULT_PATH,
    SESSION_MAX_MESSAGES_NO_LONG_MEMORY,
    SYSTEM_AGENT_URL,
    STT_SERVICE_URL,
    TTS_SERVICE_URL,
    PLAYBOOK_FEATURE_ENABLED,
    CENTRAL_MODEL_LABEL_BALANCED,
    CENTRAL_MODEL_LABEL_ECO,
    PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED,
    WEB_FETCH_ALLOWLIST_HOSTS_RAW,
    WEB_FETCH_MAX_BYTES,
    WEB_FETCH_MVP_ENABLED,
    WEB_FETCH_TIMEOUT_SEC,
    WORKSPACE_SESSION_TTL_SECONDS,
    WORKSPACE_STORE_BACKEND,
    HOST_CONTEXT_TEXT_TRIGGER_ENABLED,
    CHAT_SESSIONS_ENABLED,
    WIDGET_MULTI_SLOT_ENABLED,
    CENTRAL_MULTISLOT_AGGREGATE_MAX_CHARS,
    CENTRAL_MULTISLOT_DEFAULT_SLOT,
    CENTRAL_MULTISLOT_FIRST_TURN_INCLUDE_NEIGHBORS,
    CENTRAL_MULTISLOT_MAX_NEIGHBOR_EDGES,
    CENTRAL_MULTISLOT_NEIGHBOR_MAX_MESSAGES,
    COMPOSER_SEGMENTS_IN_STREAM_ENABLED,
    CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED,
    CENTRAL_RATE_LIMIT_ENABLED,
    CENTRAL_RATE_LIMIT_PATH_PREFIXES,
    CENTRAL_RATE_LIMIT_PER_WINDOW,
    CENTRAL_RATE_LIMIT_WINDOW_SECONDS,
)
from app.shared.approvals_store import get_approval, resolve_tenant_id_for_store
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit
from app.shared.plan import ActionPlan, build_plan_text_chat, build_plan_voice_chat
from app.shared.modality_models import (
    build_modality_invocation_entry,
    modality_composer_label,
    modality_model_display_label,
)
from app.shared.public_capabilities import get_modality_models_public
from app.shared.perception import (
    MediaAttachment,
    build_perception_enriched_block,
    resolve_perception_call_params,
)
from app.shared.profiles import PROFILES, get_active_profile
from app.shared.logging_setup import suppress_metrics_access_log
from app.shared.openapi_metadata import OPENAPI_TAG_METADATA
from app.http.auth_routes import auth_public_snapshot, router_auth
from app.shared.attachment_policy import validate_media_attachments
from app.shared.canvas_write_context import build_canvas_write_context
from app.shared.context_manager import ContextStats, prepare_history
from app.inference import effective_inference_context_cap
from app.shared.l8_pipeline_policy import (
    build_l8_inference_meta,
    effective_summarization_thresholds,
    extract_router_caps,
)
from app.shared.router_extract import slim_injected_history_for_router
from app.shared.multislot_context import (
    apply_multislot_to_compacted_history,
    build_multislot_system_message,
    effective_active_slot,
    first_turn_from_history,
    graph_neighbors,
)
from app.memory_service import build_ui_memory_context
from app.shared.web_fetch_dev import fetch_web_dev, parse_host_allowlist
from app.tools import embed_agent_tools_text
from app.rag import embed_local_hash, search_memory, upsert_memory_item
from app.context import build_stream_error_payload
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.prompt_injection import build_eco_summary_prompt
from app.tools import record_agent_tool_audit_event, record_capability_digest_injected
from app.shared.redacted_thinking import RedactedThinkingStreamSplitter, assistant_message_for_history
from app.tools import iter_agent_tool_stream, run_agent_tool_flow
from app.tools import get_agent_tools_catalog
from app.workspace import load_widget_slot_graph
from app.shared.central_product_pack import get_central_product_public_snapshot
from app.shared.system_prompt_manifest import get_system_prompt_public_snapshot
from app.shared.system_prompt_loader import build_system_prompt_injection_messages
from app.playbook import (
    build_playbook_system_message,
    list_playbook_entries_meta,
    router_playbook,
    _playbook_surface_enabled,
    _central_focus_abort,
    PlaybookCreateRequest,
    PlaybookPromotionMaterializeRequest,
    AssistantFeedbackRequest,
)
from app.shared.public_capabilities import build_widget_feature_flags
from app.health import (
    router_well_known,
    router_host,
    _service_health,
    _query_prometheus,
    _host_summary_payload_best_effort,
)
from app.inference import auto_tier_policies_public_snapshot
from app.workspace import (
    router_workspace,
    WidgetSlotGraphEdgeIn,
    WidgetSlotGraphPatchBody,
)
from app.sessions import (
    router_sessions,
    AssistantPreferencesPatchRequest,
    ChatSessionCreateBody,
    ChatSessionPatchBody,
    _require_chat_sessions_api,
)
from app.approvals import router_approvals, ApprovalTestRequest
from app.actions import router_actions
from app.inference import (
    router_inference,
    ProfileRequest,
    CloudModelAllowlistEntry,
    CloudModelsAllowlistWriteRequest,
    _ui_inference_snapshot,
    _require_resolved_llm,
    _sorted_vendor_rows_for_ui,
    _norm_vendor_q,
)
from app.rag import (
    router_rag,
    build_ui_memory_context,
    _document_rag_public_snapshot,
    _session_rag_public_snapshot,
    _agent_tools_rag_public_snapshot,
)
from app.tenant import (
    router_tenant,
    install_tenant_config_middleware,
)
from app.tenant_quota import (
    router_quota,
    check_quota,
    increment_usage,
)
from app.shared.observability import (
    router_observability,
)
from app.assistant_routes import (
    router_assistant,
    ChatMessage,
    AssistantTextRequest,
    AssistantPlanRequest,
    _workspace_store_key,
    _apply_chat_session_history,
    _resolved_assistant_payload,
    _build_injection_summary_pt,
    _build_assistant_composer_segments,
    _compose_ui_trace,
)

suppress_metrics_access_log()

# ADR-015 — validate auth production policy at startup.
from app.auth import validate_auth_production_policy
from app.config import validate_runtime_config

validate_runtime_config()
validate_auth_production_policy()

# ═══ ROUTERS ═══

router_config = APIRouter(tags=["Config"])
router_ui = APIRouter(tags=["WidgetMVP"])
router_dev = APIRouter(tags=["OpsDashboard"])


# ═══ CONFIG ═══

@router_config.get("/config", tags=['WidgetMVP', 'OpsDashboard'])
def config() -> dict[str, Any]:
    from app.connector import build_connector_status_public_snapshot
    from app.shared.pg_tenant import resolve_pg_tenant_id

    snap = _ui_inference_snapshot()
    widget_feature_flags = build_widget_feature_flags(
        model_router_configured=bool(snap.get("model_router_configured")),
        widget_multi_slot_enabled=bool(WIDGET_MULTI_SLOT_ENABLED),
        composer_segments_in_stream=bool(COMPOSER_SEGMENTS_IN_STREAM_ENABLED),
    )
    return {
        "api_host": API_HOST,
        "api_port": API_PORT,
        "stt_service_url": STT_SERVICE_URL,
        "llm_service_url": LLM_SERVICE_URL,
        "model_router_url": MODEL_ROUTER_URL or "direct (OpenRouter API)",
        "system_agent_url": SYSTEM_AGENT_URL,
        "kernel_observer_url": KERNEL_OBSERVER_URL,
        "tts_service_url": TTS_SERVICE_URL,
        "timeout_seconds": ORCHESTRATOR_TIMEOUT_SECONDS,
        "pre_injection_enabled": PRE_INJECTION_ENABLED,
        "session_max_messages_no_long_memory": SESSION_MAX_MESSAGES_NO_LONG_MEMORY,
        "agent_tools_enabled": AGENT_TOOLS_ENABLED,
        "agent_tools_few_shot_enabled": AGENT_TOOLS_FEW_SHOT_ENABLED,
        "agent_tools_few_shot_families_enabled": AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED,
        "agent_tools_json_repair_max_extra_calls": AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS,
        "agent_tools_json_schema_repair_max_extra_calls": AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS,
        "agent_tools_json_mode_enabled": AGENT_TOOLS_JSON_MODE_ENABLED,
        "agent_tools_max_executions": AGENT_TOOLS_MAX_EXECUTIONS,
        "agent_tools_rag": _agent_tools_rag_public_snapshot(),
        "document_rag": _document_rag_public_snapshot(),
        "session_rag": _session_rag_public_snapshot(),
        "workspace_store_backend": WORKSPACE_STORE_BACKEND,
        "workspace_session_ttl_seconds": WORKSPACE_SESSION_TTL_SECONDS,
        "agent_tools_catalog": get_agent_tools_catalog(),
        "host_context_text_trigger_enabled": HOST_CONTEXT_TEXT_TRIGGER_ENABLED,
        "secrets_vault_file_present": bool(SECRETS_VAULT_PATH and os.path.isfile(SECRETS_VAULT_PATH)),
        "active_ui_profile": get_active_profile(),
        "active_router_profile": snap["effective_router_profile"],
        "inference_destination": snap["inference_destination"],
        "llm_model_id": snap["llm_model_id"],
        "inference_resolve_error": snap["inference_resolve_error"],
        "capability_digest_preview": build_capability_digest_pt_br(max_chars=2600),
        "capability_digest_in_prompt_enabled": CAPABILITY_DIGEST_IN_PROMPT_ENABLED,
        "assistant_preferences": load_preferences(),
        "central_focus_mode": CENTRAL_FOCUS_MODE,
        "playbook_feature_enabled": _playbook_surface_enabled(),
        "playbook_governed_promotion_candidates_enabled": bool(
            PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED and _playbook_surface_enabled()
        ),
        "playbook_entry_count": len(list_playbook_entries_meta()) if _playbook_surface_enabled() else 0,
        "chat_sessions_enabled": CHAT_SESSIONS_ENABLED,
        "widget_multi_slot_enabled": WIDGET_MULTI_SLOT_ENABLED,
        "widget_feature_flags": dict(widget_feature_flags),
        "auto_tier_policies": auto_tier_policies_public_snapshot(),
        "llm_usage_metrics_enabled": LLM_USAGE_METRICS_ENABLED,
        "web_fetch_mvp_enabled": WEB_FETCH_MVP_ENABLED,
        "web_fetch_allowlist_configured": bool(
            WEB_FETCH_MVP_ENABLED and parse_host_allowlist(WEB_FETCH_ALLOWLIST_HOSTS_RAW)
        ),
        "system_prompt": get_system_prompt_public_snapshot(),
        "central_product": get_central_product_public_snapshot(),
        "rate_limit": {
            "enabled": bool(CENTRAL_RATE_LIMIT_ENABLED),
            "per_window": int(CENTRAL_RATE_LIMIT_PER_WINDOW),
            "window_seconds": int(CENTRAL_RATE_LIMIT_WINDOW_SECONDS),
            "path_prefixes": list(CENTRAL_RATE_LIMIT_PATH_PREFIXES),
        },
        "modality_models": get_modality_models_public(),
        "connector_status": build_connector_status_public_snapshot(
            tenant_id=resolve_pg_tenant_id(),
        ),
        **auth_public_snapshot(),
    }


# ═══ UI STATE ═══

@router_ui.get("/ui/state", tags=['WidgetMVP', 'OpsDashboard'])
def ui_state() -> dict:
    services = {
        "stt": {"status": "disabled"} if DISABLE_STT else _service_health(STT_SERVICE_URL),
        "llm": {"status": "disabled"} if DISABLE_LLM_SERVICE else _service_health(LLM_SERVICE_URL),
        "tts": {"status": "disabled"} if DISABLE_TTS else _service_health(TTS_SERVICE_URL),
        "system_agent": _service_health(SYSTEM_AGENT_URL),
        "kernel_observer": _service_health(KERNEL_OBSERVER_URL),
        "orchestrator": {"status": "ok"},
    }
    active_profile = get_active_profile()
    snap = _ui_inference_snapshot()
    active_router_profile = str(snap.get("effective_router_profile") or "")
    p95_query = (
        "histogram_quantile(0.95, "
        "sum(rate(http_request_duration_seconds_bucket[5m])) by (le,service))"
    )
    latencies: dict[str, float] = {}
    try:
        result = _query_prometheus(p95_query)
        for item in result:
            metric = item.get("metric", {})
            service = metric.get("service")
            value = item.get("value", [None, "0"])[1]
            if service:
                latencies[str(service)] = float(value)
    except (httpx.HTTPError, ValueError):
        latencies = {}

    return {
        "services": services,
        "active_profile": active_profile,
        "active_router_profile": active_router_profile,
        "inference_destination": snap.get("inference_destination"),
        "llm_model_id": snap.get("llm_model_id"),
        "inference_resolve_error": snap.get("inference_resolve_error"),
        "profiles": PROFILES,
        "latency_p95_seconds": latencies,
        "assistant_preferences": load_preferences(),
        "central_focus_mode": CENTRAL_FOCUS_MODE,
        "playbook": {
            "feature_enabled": _playbook_surface_enabled(),
            "entry_count": len(list_playbook_entries_meta()) if _playbook_surface_enabled() else 0,
        },
        "memory_context": build_ui_memory_context(),
        "chat_sessions_enabled": CHAT_SESSIONS_ENABLED,
    }


# ═══ DEV ═══

class WebFetchDevRequest(BaseModel):
    """OC-12 MVP — corpo de POST /dev/web-fetch (ADR-010)."""
    url: str = Field(..., min_length=8, max_length=4096)


@router_dev.post("/dev/web-fetch", tags=['OpsDashboard'])
def dev_web_fetch(payload: WebFetchDevRequest) -> dict[str, Any]:
    """OC-12 MVP: GET HTTP único com allowlist de host; opt-in WEB_FETCH_MVP_ENABLED (ADR-010)."""
    _central_focus_abort()
    if not WEB_FETCH_MVP_ENABLED:
        raise HTTPException(status_code=404, detail="not_found")
    allow = parse_host_allowlist(WEB_FETCH_ALLOWLIST_HOSTS_RAW)
    try:
        return fetch_web_dev(
            payload.url,
            allow_hosts=allow,
            max_bytes=WEB_FETCH_MAX_BYTES,
            timeout=WEB_FETCH_TIMEOUT_SEC,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ═══ APP FACTORY ═══

def build_empty_app_with_middleware() -> FastAPI:
    """FastAPI instance with CORS, metrics, and JWT tenant middleware (no HTTP routes until attach)."""
    from contextlib import asynccontextmanager

    from app.http.auth_context_middleware import install_auth_context_middleware
    from app.http.middleware import install_orchestrator_middleware
    from app.http.problem_details import register_exception_handlers
    from app.shared.job_dispatcher import start_job_dispatcher, stop_job_dispatcher_async

    @asynccontextmanager
    async def _orchestrator_lifespan(_app: FastAPI):
        try:
            from app.auth import ensure_bootstrap_admin

            ensure_bootstrap_admin()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("bootstrap admin skipped: %s", exc)
        start_job_dispatcher()
        yield
        await stop_job_dispatcher_async()

    application = FastAPI(
        title="Central Orchestrator API",
        openapi_tags=OPENAPI_TAG_METADATA,
        description=(
            "Erros `4xx`/`5xx` em JSON usam **RFC 9457** (`Content-Type: application/problem+json`). "
            "Validação: campo `errors[]`. Ver `docs/UI_BACKEND_CONTRACT.md` §2."
        ),
        lifespan=_orchestrator_lifespan,
    )
    register_exception_handlers(application)
    install_orchestrator_middleware(application)
    install_auth_context_middleware(application)
    install_tenant_config_middleware(application)
    from app.config import CENTRAL_PRODUCT_MODE

    if CENTRAL_PRODUCT_MODE:
        from app.shared.openapi_cli_filter import install_openapi_cli_filter

        install_openapi_cli_filter(application)
        application.description = (
            (application.description or "")
            + " **CENTRAL_PRODUCT_MODE:** OpenAPI lista só rotas CLI/widget essenciais."
        )
    return application


def attach_routes_to_app(application: FastAPI) -> None:
    """Registers domain routers; paths match UI_BACKEND_CONTRACT (Fase 1)."""
    from app.config import CENTRAL_ATENA_ENABLED, CENTRAL_PRODUCT_MODE

    application.include_router(router_auth)
    application.include_router(router_well_known)
    application.include_router(router_config)
    application.include_router(router_ui)
    if not CENTRAL_PRODUCT_MODE:
        application.include_router(router_dev)
    application.include_router(router_assistant)
    application.include_router(router_approvals)
    if not CENTRAL_PRODUCT_MODE:
        application.include_router(router_actions)
        application.include_router(router_host)
        application.include_router(router_playbook)
    from app.workspace_service import router_workspace_bind

    application.include_router(router_workspace_bind)
    application.include_router(router_workspace)
    application.include_router(router_sessions)
    application.include_router(router_inference)
    if not CENTRAL_PRODUCT_MODE:
        application.include_router(router_rag)
    application.include_router(router_tenant)
    application.include_router(router_quota)
    if not CENTRAL_PRODUCT_MODE:
        application.include_router(router_observability)
    from app.http.router_connector import router_connector as _router_connector

    application.include_router(_router_connector)

    if not CENTRAL_PRODUCT_MODE:
        from app.http.router_context_sync import router_context_sync as _router_context_sync

        application.include_router(_router_context_sync)

        if CENTRAL_ATENA_ENABLED:
            from app.atena.router import router_atena

            application.include_router(router_atena)

        from app.agent_tree import router_agent_tree as _router_agent_tree

        application.include_router(_router_agent_tree)

    from app.user_config import router_user_config
    from app.team_config import router_team
    from app.admin_routes import router_admin
    from app.work_queue import router_work_queue

    application.include_router(router_user_config)
    application.include_router(router_team)
    application.include_router(router_admin)
    application.include_router(router_work_queue)
    from app.timeline_routes import router_timeline

    application.include_router(router_timeline)
    from app.policy_admin_routes import router_policy_admin

    application.include_router(router_policy_admin)
    from app.assistant_plan_routes import router_plan

    application.include_router(router_plan)
    from app.connector_inference_routes import router_connector_inference

    application.include_router(router_connector_inference)
    from app.http.ws_connector import router_ws

    application.include_router(router_ws)
    from app.integrations_routes import router_integrations

    application.include_router(router_integrations)


def create_app() -> FastAPI:
    """Application factory for tests and ASGI servers."""
    from app.config import CENTRAL_JSON_LOGGING

    if CENTRAL_JSON_LOGGING:
        from app.shared.observability import install_json_logging

        install_json_logging()
    application = build_empty_app_with_middleware()
    attach_routes_to_app(application)
    return application


app = create_app()
