"""Assistant domain — text/stream/voice pipeline, injection, trace, SSE."""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.shared.plan import build_plan_text_chat, build_plan_voice_chat
from app.shared.attachment_policy import validate_media_attachments
from app.shared.assistant_hybrid_pipeline import (
    iter_ndjson_lines_with_stream_fallback,
    record_pipeline_decision,
)
from app.shared.canvas_write_context import build_canvas_write_context
from app.clients import call_llm, call_stt, call_tts
from app.config import (
    AGENT_TOOLS_ENABLED,
    AGENT_TOOLS_MAX_EXECUTIONS,
    CAPABILITY_DIGEST_IN_PROMPT_ENABLED,
    CENTRAL_FOCUS_MODE,
    CENTRAL_MODEL_LABEL_BALANCED,
    CENTRAL_MODEL_LABEL_ECO,
    CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED,
    CHAT_SESSIONS_ENABLED,
    CONTEXT_PIPELINE_ENABLED,
    HOST_CONTEXT_TEXT_TRIGGER_ENABLED,
    MVP_MODE,
    PRE_INJECTION_ENABLED,
    PRE_INJECTION_FILE_PATH,
)
from app.context import build_stream_error_payload, record_assistant_thinking
from app.shared.host_context_trigger import should_inject_host_context_from_text
from app.shared.perception import MediaAttachment
from app.shared.modality_models import build_modality_invocation_entry, modality_composer_label, modality_model_display_label
from app.shared.orchestrator_audit import write_event as write_orchestrator_audit
from app.shared.perception import build_perception_enriched_block, resolve_perception_call_params
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.platform_context import include_platform_host_context
from app.shared.prompt_injection import build_eco_summary_prompt
from app.tools import record_agent_tool_audit_event, record_capability_digest_injected
from app.shared.redacted_thinking import RedactedThinkingStreamSplitter, assistant_message_for_history
from app.tools import iter_agent_tool_stream, run_agent_tool_flow
from app.shared.context_manager import ContextStats
from app.shared.l8_pipeline_policy import build_l8_inference_meta
from app.inference import effective_inference_context_cap, resolve_llm_for_assistant_request
from app.sessions import history_dicts_for_prepare, append_completed_turn
from app.repositories.preferences_repository import load_preferences, preferences_system_messages
from app.shared.ambientacao import (
    build_capability_digest_system_message,
    build_pre_injection_message,
    get_pre_injection_body,
)
from app.shared.workspace_context import set_request_workspace_root
from app.workspace_service import resolve_effective_workspace_root
from app.shared.system_prompt_manifest import get_system_prompt_public_snapshot

# ═══ ROUTER ═══

router_assistant = APIRouter()


def _require_context_pipeline() -> None:
    if not CONTEXT_PIPELINE_ENABLED:
        raise HTTPException(status_code=503, detail="ContextPipeline is disabled on this server")

def _workspace_path_from_request(request: Request) -> str | None:
    """Return effective workspace root (legacy — from header or persisted binding)."""
    if request is None:
        return None
    raw = (request.headers.get("X-Central-Workspace") or "").strip()
    ws_id = (request.headers.get("X-Central-Workspace-Id") or "").strip()
    return resolve_effective_workspace_root(raw or None, header_workspace_id=ws_id or None)


def _connector_id_from_binding() -> str | None:
    """Return connector_id from the current workspace binding, if any."""
    from app.workspace_service import get_workspace_binding
    binding = get_workspace_binding()
    if binding:
        return binding.get("connector_id")
    return None


def _assemble_via_pipeline(
    payload: AssistantTextRequest,
    rid: str,
    *,
    agent_name: str | None,
    connector_alive: bool,
    mode: str,
    workspace_path: str | None,
    connector_id: str | None = None,
) -> Any:
    from app.context_pipeline import ContextPipeline

    _require_context_pipeline()
    pipeline = ContextPipeline()
    return pipeline.assemble(
        payload,
        rid,
        agent_name=agent_name,
        connector_alive=connector_alive,
        mode=mode,
        workspace_path=workspace_path,
        connector_id=connector_id,
        tenant_id=resolve_pg_tenant_id(),
    )

class ChatMessage(BaseModel):
    role: str = Field(..., description="system | user | assistant")
    content: str


class ClarifyResponseInput(BaseModel):
    interrupt_id: str = Field(..., min_length=8, max_length=64)
    choice: str | None = Field(default=None, max_length=500)
    custom: str | None = Field(default=None, max_length=2000)


class AssistantTextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    output_filename: str | None = None
    request_id: str | None = None
    workspace_session_id: str | None = Field(
        default=None,
        max_length=200,
        description="F1/A1: chave estável do workspace/canvas entre POSTs; omissão usa request_id no store in-process.",
    )
    chat_session_id: str | None = Field(
        default=None,
        max_length=200,
        description="Com CHAT_SESSIONS_ENABLED: histórico lido do servidor para esta sessão; `history` do cliente é ignorado.",
    )
    # Pos-injecao: so quando True (politica ambientacao; sessao actual em `history` segue sempre, com truncagem se False)
    include_long_session_memory: bool = Field(
        default=False,
        description="Eco-compactacao + resumo persistido",
    )
    include_memory_recall: bool = Field(
        default=False,
        description="Recall de memória externa (Postgres+pgvector) para esta query",
    )
    include_document_rag: bool = Field(
        default=False,
        description="F5: injecta excertos semânticos de documento indexado (document_rag_doc_id)",
    )
    document_rag_doc_id: str | None = Field(
        default=None,
        max_length=128,
        description="F5: id lógico do documento (ingest scripts/ingest_document_rag.py)",
    )
    include_session_rag: bool = Field(
        default=True,
        description="F5: recall semântico do namespace session (requer chat_session_id; pós-turno indexa factos)",
    )
    include_host_context: bool = Field(
        default=False,
        description="Injeta JSON agregado system-agent + kernel-observer (read-only)",
    )
    use_agent_tools: bool = Field(
        default=False,
        description="Fase F: loop JSON + tool P0 get_host_summary (requer AGENT_TOOLS_ENABLED no servidor)",
    )
    use_saved_assistant_defaults: bool = Field(
        default=False,
        description="L2: quando True, aplica default_include_* e default_use_agent_tools de state/assistant_preferences.json",
    )
    include_playbook: bool = Field(
        default=False,
        description="L3: quando True e PLAYBOOK_FEATURE_ENABLED, injeta bloco system com snippets do playbook local (RAG léxico)",
    )
    include_capability_digest: bool = Field(
        default=False,
        description="L0-2: quando True e CAPABILITY_DIGEST_IN_PROMPT_ENABLED, injecta digest de capacidades no system (apos pre-injecao)",
    )
    media_attachments: list[MediaAttachment] = Field(
        default_factory=list,
        description="Imagens/áudio em base64: percepção via perfil eco antes do balanced",
    )
    widget_active_slot: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description="Slot activo 1–4 (multi-slot); v1: telemetria / futuro contexto cross-slot.",
    )
    # T15 — Context Engine: optional agent name for multi-agent routing
    agent_name: str | None = Field(
        default=None,
        max_length=128,
        description="T15: nome do agente (ex: 'default', 'coder', 'reviewer'). Sem tree_id → flat mode com agent default.",
    )
    clarify_response: ClarifyResponseInput | None = Field(
        default=None,
        description="Fase 2b: resposta a card clarify (choice 1–4 ou custom)",
    )
    model_override: str | None = Field(
        default=None,
        max_length=256,
        description="Override de modelo só neste pedido; validado contra governança (sem bypass).",
    )

    @field_validator("workspace_session_id", mode="before")
    @classmethod
    def _normalize_workspace_session_id(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("workspace_session_id must be a string")
        s = v.strip()
        if not s:
            return None
        if len(s) < 8:
            raise ValueError("workspace_session_id must be at least 8 characters when provided")
        return s

    @field_validator("chat_session_id", mode="before")
    @classmethod
    def _normalize_chat_session_id(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("chat_session_id must be a string")
        s = v.strip()
        if not s:
            return None
        if len(s) < 8:
            raise ValueError("chat_session_id must be at least 8 characters when provided")
        return s






class AssistantPlanRequest(BaseModel):
    text: str = Field(..., min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    request_id: str | None = None
    mode: Literal["text", "voice"] = Field(
        default="text",
        description="text = plano do fluxo assistant/text; voice = plano do fluxo assistant/voice",
    )
    include_capability_digest: bool = Field(
        default=False,
        description="Opt-in declarado no pedido (sem inject no plano); audit apenas",
    )


def _workspace_store_key(payload: AssistantTextRequest, request_id: str) -> str:
    """Chave do store de canvas in-process (F1). Com ``workspace_session_id`` no corpo, mantém artefactos entre POSTs."""
    if payload.workspace_session_id:
        return payload.workspace_session_id
    return request_id

def _apply_chat_session_history(payload: AssistantTextRequest) -> AssistantTextRequest:
    """Com sessão persistida, o histórico vem do ficheiro — ignora `history` enviado pelo cliente."""
    if not CHAT_SESSIONS_ENABLED:
        return payload
    sid = (payload.chat_session_id or "").strip()
    if not sid:
        return payload
    rows = history_dicts_for_prepare(sid)
    if rows is None:
        raise HTTPException(status_code=400, detail="chat_session_not_found")
    return payload.model_copy(
        update={"history": [ChatMessage(role=str(r["role"]), content=str(r["content"])) for r in rows]}
    )


def _apply_clarify_response(payload: AssistantTextRequest) -> AssistantTextRequest:
    """Merge clarify card answer into user text and advance session phase."""
    if not payload.clarify_response:
        sid = (payload.chat_session_id or "").strip()
        if sid and CHAT_SESSIONS_ENABLED:
            from app.session_surface_service import set_session_phase

            set_session_phase(sid, "streaming")
        return payload
    sid = (payload.chat_session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="clarify_requires_chat_session_id")
    from app.session_surface_service import consume_clarify_response

    cr = payload.clarify_response
    try:
        answer = consume_clarify_response(
            sid,
            interrupt_id=cr.interrupt_id,
            choice=cr.choice,
            custom=cr.custom,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    merged = f"{payload.text.strip()}\n\n[Clarify] {answer}"
    return payload.model_copy(update={"text": merged, "clarify_response": None})


def _resolved_assistant_payload(payload: AssistantTextRequest) -> AssistantTextRequest:
    """L2: opcionalmente aplica defaults persistidos em assistant_preferences.json."""
    if payload.use_saved_assistant_defaults:
        prefs = load_preferences()
        payload = payload.model_copy(
            update={
                "include_long_session_memory": bool(prefs["default_include_long_session_memory"]),
                "include_memory_recall": bool(prefs.get("default_include_memory_recall", False)),
                "include_host_context": bool(prefs["default_include_host_context"]),
                "include_playbook": bool(prefs.get("default_include_playbook", False)),
                "include_capability_digest": bool(prefs.get("default_include_capability_digest", False)),
                "use_agent_tools": bool(prefs["default_use_agent_tools"]),
            }
        )
    if CENTRAL_FOCUS_MODE:
        return payload.model_copy(
            update={
                "include_long_session_memory": False,
                "include_memory_recall": False,
                "include_document_rag": False,
                "document_rag_doc_id": None,
                "include_session_rag": False,
                "include_playbook": False,
                "include_host_context": False,
            }
        )
    return payload

def _build_injection_summary_pt(
    *,
    payload: AssistantTextRequest,
    inject_host_context: bool,
    host_context_text_trigger_match: bool,
    meta: dict[str, Any],
    agent_tools_effective: bool,
) -> str:
    """Resumo curto para a UI (sem corpo de system messages nem paths)."""
    parts: list[str] = []
    if payload.use_saved_assistant_defaults:
        parts.append(
            "Preferências L2 aplicaram os defaults de máquina/playbook/ferramentas neste pedido."
        )
    parts.append(
        "Pedido efectivo (campos enviados após defaults): "
        f"contexto de máquina={payload.include_host_context}, "
        f"playbook={payload.include_playbook}, "
        f"digest capacidades={payload.include_capability_digest}, "
        f"ferramentas={payload.use_agent_tools}, "
        f"memória longa={payload.include_long_session_memory}, "
        f"recall memória={bool(payload.include_memory_recall)}, "
        f"RAG documento={bool(payload.include_document_rag)}."
    )
    if host_context_text_trigger_match:
        parts.append(
            "O servidor injectou o bloco factual do host por gatilho de texto (checkbox de máquina desligada)."
        )
    if inject_host_context and not host_context_text_trigger_match:
        parts.append("Bloco factual do host incluído conforme o pedido.")
    if meta.get("pre_injection_applied"):
        parts.append("Pré-injeção institucional incluída (conteúdo omitido na UI).")
    if meta.get("system_prompt_bundled_applied") or meta.get("system_prompt_overlay_applied"):
        b = int(meta.get("system_prompt_bundled_chars") or 0)
        o = int(meta.get("system_prompt_overlay_chars") or 0)
        l6 = bool(meta.get("system_prompt_l6_anchor_applied"))
        parts.append(
            f"SYSTEM versionado (Fase 11): âncora L6={l6}, bundled≈{b} chars, overlay≈{o} chars (corpo omitido na UI)."
        )
    elif meta.get("system_prompt_l6_anchor_applied"):
        parts.append("SYSTEM: apenas âncora L6 injectada (bundled/overlay vazios ou desligados).")
    if meta.get("capability_digest_block_applied"):
        parts.append(
            "Digest L0-2 de capacidades injectado no system (mapa read-only/HITL; não é permissão de execução)."
        )
    n_pref = int(meta.get("preferences_system_message_count") or 0)
    if n_pref > 0:
        parts.append(f"Mensagens system de preferências L2: {n_pref} (texto omitido).")
    if meta.get("host_context_block_applied"):
        parts.append(
            "Resumo read-only do host (system-agent + kernel-observer + auditd quando disponível); "
            "correlacionável com request_id; sem secrets na resposta da API."
        )
    if meta.get("memory_recall_system_applied"):
        parts.append("Passagens de memória externa incluídas no system (corpo omitido na UI).")
    if meta.get("document_rag_applied"):
        n = int(meta.get("document_rag_chunk_count") or 0)
        did = str(meta.get("document_rag_doc_id") or "")
        parts.append(
            f"Excertos de documento indexado (F5) incluídos no system: doc_id={did}, chunks≈{n} (texto omitido na UI)."
        )
    elif payload.include_document_rag and (payload.document_rag_doc_id or "").strip():
        parts.append(
            "RAG de documento pedido, mas nenhum excerto recuperado (índice vazio, modelo de embedding diferente do ingest, ou DOCUMENT_RAG_SERVER_ENABLED=0)."
        )
    if meta.get("playbook_block_applied"):
        parts.append("Snippets do playbook local incluídos (corpo omitido na UI).")
    if meta.get("multislot"):
        ms = meta["multislot"]
        if isinstance(ms, dict):
            slots = ms.get("injected_slots")
            trunc = ms.get("truncated")
            parts.append(
                f"Multi-slot (Fase 9): slots injectados={slots}, truncado={trunc} "
                "(detalhe em inference_meta.multislot no stream)."
            )
    if agent_tools_effective:
        parts.append("Ferramentas do agente (P0) activas neste pedido.")
    elif payload.use_agent_tools and not agent_tools_effective:
        parts.append("Ferramentas pedidas mas desactivadas no servidor (AGENT_TOOLS_ENABLED).")
    if payload.include_capability_digest and not meta.get("capability_digest_block_applied"):
        parts.append(
            "Digest de capacidades pedido, mas não injectado (CAPABILITY_DIGEST_IN_PROMPT_ENABLED=0 ou digest vazio)."
        )
    return " ".join(parts)

def _build_assistant_composer_segments(
    *,
    router_profile: str,
    model_override: str,
    auto_tier: str,
    perception_modality_role: str = "",
    perception_model_id: str = "",
    modality_tool_invocations: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """ADR-016 §7 — primary + optional auxiliary segments (perception / modality tools)."""
    segments: list[dict[str, Any]] = []
    aux_idx = 0

    def _aux_segment(role: str, model_id: str, label: str) -> None:
        nonlocal aux_idx
        if not role or not model_id:
            return
        segments.append(
            {
                "schema_version": 1,
                "segment_id": f"aux-{aux_idx}",
                "role": "auxiliary",
                "label": label,
                "modality_role": role,
                "model_id": model_id,
                "router_profile": None,
                "auto_tier": None,
                "tokens_input": None,
                "tokens_output": None,
            }
        )
        aux_idx += 1

    if perception_modality_role and perception_model_id:
        _aux_segment(
            perception_modality_role,
            perception_model_id,
            modality_composer_label(perception_modality_role),
        )
    for inv in modality_tool_invocations or []:
        role = str(inv.get("modality_role") or "").strip()
        mid = str(inv.get("model_id") or "").strip()
        if not role or not mid:
            continue
        label = str(inv.get("label_pt") or "").strip() or modality_composer_label(role)
        _aux_segment(role, mid, label)

    tier_done = str(auto_tier or "").strip()
    mid_eff = str(model_override or "").strip()
    segments.append(
        {
            "schema_version": 1,
            "segment_id": "primary-0",
            "role": "primary",
            "label": "Resposta",
            "model_id": mid_eff,
            "router_profile": router_profile,
            "auto_tier": tier_done or None,
            "tokens_input": None,
            "tokens_output": None,
        }
    )
    return segments

def _compose_ui_trace(
    payload: AssistantTextRequest,
    *,
    inject_host_context: bool,
    host_context_text_trigger_match: bool,
    injection_meta: dict[str, Any],
    agent_tools_effective: bool,
    modality_role: str | None = None,
    model_id: str | None = None,
    modality_invocations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "use_saved_assistant_defaults": bool(payload.use_saved_assistant_defaults),
        "workspace_session_id": payload.workspace_session_id,
        "chat_session_id": payload.chat_session_id,
        "request_flags": {
            "include_host_context": bool(payload.include_host_context),
            "include_playbook": bool(payload.include_playbook),
            "include_capability_digest": bool(payload.include_capability_digest),
            "use_agent_tools": bool(payload.use_agent_tools),
            "include_long_session_memory": bool(payload.include_long_session_memory),
            "include_memory_recall": bool(payload.include_memory_recall),
            "include_document_rag": bool(payload.include_document_rag),
            "document_rag_doc_id": payload.document_rag_doc_id,
        },
        "injection_applied": dict(injection_meta),
        "compaction": dict(injection_meta.get("compaction") or {}),
        "summary_version": (injection_meta.get("compaction") or {}).get("summary_version"),
        "token_accounting": dict(injection_meta.get("token_accounting") or {}),
        "host_context_text_trigger_match": bool(host_context_text_trigger_match),
        "inject_host_context": bool(inject_host_context),
        "agent_tools_request": bool(payload.use_agent_tools),
        "agent_tools_effective": bool(agent_tools_effective),
        "injection_summary_pt": _build_injection_summary_pt(
            payload=payload,
            inject_host_context=inject_host_context,
            host_context_text_trigger_match=host_context_text_trigger_match,
            meta=injection_meta,
            agent_tools_effective=agent_tools_effective,
        ),
        "system_prompt": get_system_prompt_public_snapshot(),
    }
    mr = (modality_role or "").strip()
    mid = (model_id or "").strip()
    if mr:
        trace["modality_role"] = mr
    if mid:
        trace["model_id"] = mid
    if modality_invocations:
        trace["modality_invocations"] = list(modality_invocations)
    return trace


def _sse_line(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_canvas_html(reply: str) -> str | None:
    """Extrai blocos HTML da resposta para o LiveCanvas.

    Detecta conteúdo entre ```html ... ``` ou tags HTML substanciais.
    Retorna o HTML extraído ou None.
    """
    import re

    if not reply or len(reply) < 20:
        return None

    # Tenta extrair de bloco ```html ... ```
    m = re.search(r"```html\s*\n(.*?)```", reply, re.DOTALL | re.IGNORECASE)
    if m:
        html = m.group(1).strip()
        if len(html) > 50:
            return html

    # Tenta extrair de bloco ``` ... ``` genérico com conteúdo HTML
    m = re.search(r"```\s*\n(<!DOCTYPE|<html|<div|<body|<head)", reply, re.DOTALL)
    if m:
        start = m.start()
        end = reply.find("```", start + 10)
        if end > start:
            html = reply[start + 3 : end].strip()
            if html.startswith("```"):
                html = html[3:].strip()
            if len(html) > 50 and ("<html" in html or "<div" in html):
                return html

    return None

ASSISTANT_SSE_DONE_SCHEMA_VERSION = 1

@router_assistant.post("/assistant/plan", tags=['OpsDashboard'])
def assistant_plan(payload: AssistantPlanRequest) -> dict[str, Any]:
    """Apenas plano estruturado — nao executa LLM/STT/TTS."""
    _central_focus_abort()
    rid = payload.request_id or str(uuid4())
    plan: ActionPlan = (
        build_plan_voice_chat(rid) if payload.mode == "voice" else build_plan_text_chat(rid)
    )
    intent_preview = payload.text.strip()[:200]
    write_orchestrator_audit(
        {
            "event": "plan_requested",
            "request_id": rid,
            "mode": payload.mode,
            "intent_summary": intent_preview,
            "plan": plan.model_dump(),
            "include_capability_digest": bool(payload.include_capability_digest),
            "capability_digest_server_enabled": bool(CAPABILITY_DIGEST_IN_PROMPT_ENABLED),
        }
    )
    return {"request_id": rid, "plan": plan.model_dump()}


@router_assistant.post("/assistant/text", tags=['OpsDashboard'])
def assistant_text(payload: AssistantTextRequest, request: Request) -> dict[str, Any]:
    payload = _apply_clarify_response(_apply_chat_session_history(_resolved_assistant_payload(payload)))
    rid = payload.request_id or str(uuid4())
    ws_path = _workspace_path_from_request(request)
    set_request_workspace_root(ws_path)
    ws_key = _workspace_store_key(payload, rid)
    canvas_wctx = build_canvas_write_context(
        payload.widget_active_slot,
        chat_session_id=payload.chat_session_id,
        tenant_id=resolve_pg_tenant_id(),
    )
    plan = build_plan_text_chat(rid)
    intent_preview = payload.text.strip()[:200]
    enriched_by_perception = ""
    perception_model_id = ""
    perception_modality_role = ""
    try:
        if payload.media_attachments:
            validate_media_attachments(list(payload.media_attachments))
            perception_modality_role, prof, mo = resolve_perception_call_params(
                list(payload.media_attachments)
            )
            perception_model_id = mo
            enriched_by_perception = build_perception_enriched_block(
                payload.text,
                list(payload.media_attachments),
                profile=prof,
                model_override=mo,
                modality_role=perception_modality_role,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError:
        enriched_by_perception = (
            "[Percepção indisponível — não foi possível processar anexos.]"
        )
    effective_text = (
        f"{enriched_by_perception}\n\n{payload.text}" if enriched_by_perception else payload.text
    )
    payload_for_prepare = payload.model_copy(update={"text": effective_text})
    if CENTRAL_FOCUS_MODE:
        host_context_trigger_match = False
        inject_host_context = False
    else:
        platform_host = include_platform_host_context()
        host_context_trigger_match = (
            platform_host
            and HOST_CONTEXT_TEXT_TRIGGER_ENABLED
            and not payload.include_host_context
            and should_inject_host_context_from_text(payload.text)
        )
        inject_host_context = bool(
            platform_host and (payload.include_host_context or host_context_trigger_match)
        )
    write_orchestrator_audit(
        {
            "event": "assistant_text_start",
            "request_id": rid,
            "intent_summary": intent_preview,
            "plan": plan.model_dump(),
            "include_long_session_memory": payload.include_long_session_memory,
            "include_memory_recall": payload.include_memory_recall,
            "include_document_rag": payload.include_document_rag,
            "document_rag_doc_id": payload.document_rag_doc_id,
            "include_host_context": payload.include_host_context,
            "host_context_text_trigger_match": host_context_trigger_match,
            "inject_host_context": inject_host_context,
            "use_agent_tools": payload.use_agent_tools,
            "use_saved_assistant_defaults": payload.use_saved_assistant_defaults,
            "include_playbook": payload.include_playbook,
            "include_capability_digest": payload.include_capability_digest,
            "capability_digest_server_enabled": bool(CAPABILITY_DIGEST_IN_PROMPT_ENABLED),
            "media_attachments": len(payload.media_attachments),
            "chat_session_id": payload.chat_session_id,
            "widget_active_slot": payload.widget_active_slot,
        }
    )
    try:
        agent_name = (payload.agent_name or "").strip() or None
        workspace_path = _workspace_path_from_request(request)
        mode = "cli" if workspace_path else "web"

        assembled = _assemble_via_pipeline(
            payload_for_prepare,
            rid,
            agent_name=agent_name,
            connector_alive=bool(workspace_path),
            mode=mode,
            workspace_path=workspace_path,
            connector_id=_connector_id_from_binding(),
        )
        injected_history = assembled.injected_history
        ctx_stats = assembled.ctx_stats
        session_truncated = assembled.session_truncated
        recall_count = assembled.recall_count
        # (stream handler)
        injection_meta = assembled.injection_meta
        pipeline_tools = assembled.openai_tools

        injection_meta["t15"] = {"context_pipeline": True}
        ui_trace = _compose_ui_trace(
            payload,
            inject_host_context=inject_host_context,
            host_context_text_trigger_match=host_context_trigger_match,
            injection_meta=injection_meta,
            agent_tools_effective=bool(AGENT_TOOLS_ENABLED and payload.use_agent_tools),
            modality_role=perception_modality_role or None,
            model_id=perception_model_id or None,
        )

        tools_profile, router_profile, model_override = resolve_llm_for_assistant_request(payload)
        agent_meta: dict[str, Any] = {}
        digest_audit_flag = bool(injection_meta.get("capability_digest_block_applied"))
        if AGENT_TOOLS_ENABLED and payload.use_agent_tools:

            def _tool_audit(ev: dict[str, Any]) -> None:
                ev2 = {**ev, "capability_digest_in_prompt": digest_audit_flag}
                record_agent_tool_audit_event(ev2)
                write_orchestrator_audit({"request_id": rid, **ev2})

            reply, agent_meta = run_agent_tool_flow(
                user_text=effective_text,
                base_history=injected_history,
                request_id=rid,
                profile=tools_profile,
                max_tool_executions=max(1, AGENT_TOOLS_MAX_EXECUTIONS),
                audit=_tool_audit,
                model_override=model_override,
                workspace_store_key=ws_key,
                canvas_write_ctx=canvas_wctx,
                chat_session_id=(payload.chat_session_id or "").strip() or None,
            )
        else:
            reply = call_llm(
                effective_text,
                injected_history,
                profile=router_profile,
                model_override=model_override,
                tools=pipeline_tools if pipeline_tools else None,
            )

        audio_file = call_tts(reply, payload.output_filename)
        if CHAT_SESSIONS_ENABLED and (payload.chat_session_id or "").strip():
            try:
                append_completed_turn(
                    (payload.chat_session_id or "").strip(),
                    user_text=payload.text,
                    assistant_text=reply,
                    active_slot=payload.widget_active_slot,
                )
            except Exception:
                pass
        write_orchestrator_audit(
            {
                "event": "assistant_text_done",
                "request_id": rid,
                "intent_summary": intent_preview,
                "plan": plan.model_dump(),
                "context_compacted": ctx_stats.compacted,
                "history_messages_before": ctx_stats.history_messages_before,
                "history_messages_after": ctx_stats.history_messages_after,
                "history_chars_before": ctx_stats.history_chars_before,
                "history_chars_after": ctx_stats.history_chars_after,
                "summary_chars": ctx_stats.summary_chars,
                # Campos legados removidos.
                # Novos campos: memória externa (Postgres+pgvector).
                "memory_enabled": True,
                "memory_recall_count": recall_count,
                "pre_injection": bool(PRE_INJECTION_ENABLED),
                "post_injection_host": inject_host_context,
                "host_context_from_text_trigger": host_context_trigger_match,
                "post_injection_memory": bool(payload.include_memory_recall),
                "post_injection_document_rag": bool(injection_meta.get("document_rag_applied")),
                "document_rag_chunk_count": int(injection_meta.get("document_rag_chunk_count") or 0),
                "document_rag_doc_id": injection_meta.get("document_rag_doc_id"),
                "long_session_memory": payload.include_long_session_memory,
                "session_truncated": session_truncated,
                "include_playbook": payload.include_playbook,
                "include_capability_digest": payload.include_capability_digest,
                "capability_digest_block_applied": bool(
                    injection_meta.get("capability_digest_block_applied")
                ),
                "agent_tools": agent_meta,
                "result_ok": True,
            }
        )
        return {
            "request_id": rid,
            "transcript": payload.text,
            "reply": reply,
            "audio_file": audio_file,
            "plan": plan.model_dump(),
            "ui_trace": ui_trace,
        }
    except (httpx.HTTPError, RuntimeError) as exc:
        write_orchestrator_audit(
            {
                "event": "assistant_text_error",
                "request_id": rid,
                "intent_summary": intent_preview,
                "plan": plan.model_dump(),
                "error": str(exc),
            }
        )
        raise HTTPException(status_code=502, detail=f"Falha no fluxo text->llm->tts: {exc}") from exc

@router_assistant.post("/assistant/text/stream", tags=['WidgetMVP'])
async def assistant_text_stream(request: Request, payload: AssistantTextRequest) -> StreamingResponse:
    """
    Server-Sent Events (SSE):
    - `start` — `{ "request_id": "...", "ui_trace": { ... } }` (transparência UX: flags efectivas + resumo de injecção)
    - `model_swap` — aviso curto (ex. após percepção multimodal eco → texto para o perfil principal)
    - `thinking` — `{ "d": "fragmento" }` — raciocínio do modelo (DeepSeek / tags thinking), separado do texto final
    - `thinking_done` — `{}` — fim do bloco de raciocínio no stream
    - `token` — `{ "d": "fragmento" }` (resposta ao utilizador; com agent tools, pode incluir o texto de `final` antes de `tool_proposed` quando o modelo envia ambos)
    - Com `use_agent_tools` e `AGENT_TOOLS_ENABLED`: `tool_proposed`, `tool_running`, `tool_result`, `tool_denied`
    - `done` — `{ "request_id", "schema_version", "reply", "plan", "composer_segments", "agent_tools"? }`
    - `error` — Problem Details (RFC 9457) + `message`, `code`, `turn_not_persisted`, `user_message_pt` (D8; sem `done` nem persistência de sessão)
    Fechar a conexão (Abort no cliente) deve parar a geração: verificações
    ``await request.is_disconnected()`` entre eventos e ``close()`` no iterador
    NDJSON para libertar o stream HTTP ao model-router quando possível.
    """
    payload = _apply_clarify_response(_apply_chat_session_history(_resolved_assistant_payload(payload)))
    from app.shared.dlp_scanner import scan_prompt_text

    dlp = scan_prompt_text(payload.text)
    if not dlp.allowed:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "DLP Policy Violation",
                "status": 422,
                "detail": dlp.message_pt or "Conteúdo bloqueado pela política DLP.",
                "hits": dlp.hits,
            },
        )
    rid = payload.request_id or str(uuid4())
    ws_path = _workspace_path_from_request(request)
    set_request_workspace_root(ws_path)
    # T4: concurrent stream limiter — acquire slot before processing
    from app.shared.concurrent_limiter import acquire as _stream_acquire, release as _stream_release, active_count as _stream_active

    stream_tid = resolve_pg_tenant_id()
    if payload.chat_session_id:
        from app.shared.log_context import set_log_context

        set_log_context(session_id=str(payload.chat_session_id))
    if not await _stream_acquire(stream_tid):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=429,
            content={
                "type": "about:blank",
                "title": "Concurrent Stream Limit Exceeded",
                "status": 429,
                "detail": "Limite de streams simultâneos excedido. Tente novamente.",
                "active_streams": _stream_active(stream_tid),
            },
            headers={"Retry-After": "5"},
        )
    ws_key = _workspace_store_key(payload, rid)
    canvas_wctx = build_canvas_write_context(
        payload.widget_active_slot,
        chat_session_id=payload.chat_session_id,
        tenant_id=resolve_pg_tenant_id(),
    )
    plan = build_plan_text_chat(rid)
    intent_preview = payload.text.strip()[:200]
    enriched_by_perception = ""
    perception_model_id = ""
    perception_modality_role = ""
    try:
        if payload.media_attachments:
            validate_media_attachments(list(payload.media_attachments))
            perception_modality_role, prof, mo = resolve_perception_call_params(
                list(payload.media_attachments)
            )
            perception_model_id = mo
            enriched_by_perception = build_perception_enriched_block(
                payload.text,
                list(payload.media_attachments),
                profile=prof,
                model_override=mo,
                modality_role=perception_modality_role,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError:
        enriched_by_perception = (
            "[Percepção indisponível — não foi possível processar anexos.]"
        )
    effective_text = (
        f"{enriched_by_perception}\n\n{payload.text}" if enriched_by_perception else payload.text
    )
    payload_for_prepare = payload.model_copy(update={"text": effective_text})
    if CENTRAL_FOCUS_MODE:
        host_context_trigger_match = False
        inject_host_context = False
    else:
        platform_host = include_platform_host_context()
        host_context_trigger_match = (
            platform_host
            and HOST_CONTEXT_TEXT_TRIGGER_ENABLED
            and not payload.include_host_context
            and should_inject_host_context_from_text(payload.text)
        )
        inject_host_context = bool(
            platform_host and (payload.include_host_context or host_context_trigger_match)
        )
    stream_use_tools = bool(AGENT_TOOLS_ENABLED and payload.use_agent_tools)
    write_orchestrator_audit(
        {
            "event": "assistant_text_stream_start",
            "request_id": rid,
            "intent_summary": intent_preview,
            "plan": plan.model_dump(),
            "include_long_session_memory": payload.include_long_session_memory,
            "include_memory_recall": payload.include_memory_recall,
            "include_document_rag": payload.include_document_rag,
            "document_rag_doc_id": payload.document_rag_doc_id,
            "include_host_context": payload.include_host_context,
            "host_context_text_trigger_match": host_context_trigger_match,
            "inject_host_context": inject_host_context,
            "use_agent_tools": stream_use_tools,
            "use_saved_assistant_defaults": payload.use_saved_assistant_defaults,
            "include_playbook": payload.include_playbook,
            "include_capability_digest": payload.include_capability_digest,
            "capability_digest_server_enabled": bool(CAPABILITY_DIGEST_IN_PROMPT_ENABLED),
            "media_attachments": len(payload.media_attachments),
            "chat_session_id": payload.chat_session_id,
            "widget_active_slot": payload.widget_active_slot,
        }
    )

    try:
        agent_name = (payload.agent_name or "").strip() or None
        workspace_path = _workspace_path_from_request(request)
        mode = "cli" if workspace_path else "web"
        assembled = _assemble_via_pipeline(
            payload_for_prepare,
            rid,
            agent_name=agent_name,
            connector_alive=bool(workspace_path),
            mode=mode,
            workspace_path=workspace_path,
            connector_id=_connector_id_from_binding(),
        )
        injected_history = assembled.injected_history
        ctx_stats = assembled.ctx_stats
        session_truncated = assembled.session_truncated
        recall_count = assembled.recall_count
        # (stream prep handler)
        injection_meta = assembled.injection_meta
        pipeline_tools_stream = assembled.openai_tools
        injection_meta["t15"] = {"context_pipeline": True}
    except httpx.HTTPError as exc:
        write_orchestrator_audit(
            {
                "event": "assistant_text_stream_error",
                "request_id": rid,
                "intent_summary": intent_preview,
                "plan": plan.model_dump(),
                "error": str(exc),
                "phase": "prepare",
            }
        )
        raise HTTPException(status_code=502, detail=f"Falha ao preparar contexto: {exc}") from exc

    tools_profile, router_profile, model_override = resolve_llm_for_assistant_request(payload)
    prefs_at_stream = load_preferences()
    stream_modality_invocations: list[dict[str, str]] = []
    if perception_modality_role and perception_model_id:
        stream_modality_invocations.append(
            build_modality_invocation_entry(
                modality_role=perception_modality_role,
                model_id=perception_model_id,
                phase="perception",
            )
        )
    stream_ui_trace = _compose_ui_trace(
        payload,
        inject_host_context=inject_host_context,
        host_context_text_trigger_match=host_context_trigger_match,
        injection_meta=injection_meta,
        agent_tools_effective=bool(stream_use_tools),
        modality_role=perception_modality_role or None,
        model_id=perception_model_id or None,
        modality_invocations=stream_modality_invocations or None,
    )

    digest_audit_flag = bool(injection_meta.get("capability_digest_block_applied"))

    pipeline_decisions: list[dict[str, Any]] = []

    async def event_gen():
        inference_meta = {
            "router_profile": router_profile,
            "model_override": model_override,
            "auto_tier": str(prefs_at_stream.get("auto_tier") or ""),
            "tools_profile": tools_profile,
            "effective_context_cap": effective_inference_context_cap(model_override),
            "l8": build_l8_inference_meta(
                injection_meta=injection_meta,
                perception_text_block=bool(enriched_by_perception),
            ),
        }
        if stream_modality_invocations:
            inference_meta["modality_invocations"] = list(stream_modality_invocations)
        if injection_meta.get("multislot"):
            inference_meta["multislot"] = injection_meta["multislot"]
        inference_meta["system_prompt"] = get_system_prompt_public_snapshot()
        stream_sid = (payload.chat_session_id or "").strip()
        session_phase = "idle"
        if stream_sid and CHAT_SESSIONS_ENABLED:
            from app.session_surface_service import get_session_phase

            session_phase = get_session_phase(stream_sid)
        yield _sse_line(
            "start",
            {
                "request_id": rid,
                "ui_trace": stream_ui_trace,
                "inference_meta": inference_meta,
                "session_phase": session_phase,
                "chat_session_id": stream_sid or None,
            },
        )
        if await request.is_disconnected():
            write_orchestrator_audit(
                {
                    "event": "assistant_text_stream_cancelled",
                    "request_id": rid,
                    "intent_summary": intent_preview,
                    "plan": plan.model_dump(),
                    "phase": "after_start",
                }
            )
            return
        if enriched_by_perception:
            record_pipeline_decision(
                pipeline_decisions,
                phase="handoff_merge",
                from_phase="perception_aux",
                to_phase="primary_ndjson_stream",
            )
            perception_label = (
                modality_model_display_label(perception_model_id)
                if perception_model_id
                else CENTRAL_MODEL_LABEL_ECO
            )
            yield _sse_line(
                "model_swap",
                {
                    "phase": "perception_done",
                    "message": (
                        f"Percepção concluída ({perception_label}); "
                        f"a continuar com {CENTRAL_MODEL_LABEL_BALANCED}."
                    ),
                    "modality_role": perception_modality_role or None,
                    "model_id": perception_model_id or None,
                    "perception_label": perception_label,
                    "model_balanced": CENTRAL_MODEL_LABEL_BALANCED,
                },
            )
        full: list[str] = []
        err_mark: str | None = None
        agent_meta_stream: dict[str, Any] = {}
        thinking_parts: list[str] = []
        try:
            if stream_use_tools:

                def _tool_audit_stream(ev: dict[str, Any]) -> None:
                    ev2 = {**ev, "capability_digest_in_prompt": digest_audit_flag}
                    record_agent_tool_audit_event(ev2)
                    write_orchestrator_audit({"request_id": rid, **ev2})

                meta_holder: dict[str, Any] = {}
                try:
                    for ev_name, data in iter_agent_tool_stream(
                        user_text=effective_text,
                        base_history=injected_history,
                        request_id=rid,
                        profile=tools_profile,
                        max_tool_executions=max(1, AGENT_TOOLS_MAX_EXECUTIONS),
                        audit=_tool_audit_stream,
                        meta_holder=meta_holder,
                        model_override=model_override,
                        workspace_store_key=ws_key,
                        canvas_write_ctx=canvas_wctx,
                        modality_invocations_out=stream_modality_invocations,
                        chat_session_id=(payload.chat_session_id or "").strip() or None,
                    ):
                        if await request.is_disconnected():
                            write_orchestrator_audit(
                                {
                                    "event": "assistant_text_stream_cancelled",
                                    "request_id": rid,
                                    "intent_summary": intent_preview,
                                    "plan": plan.model_dump(),
                                    "phase": "agent_tools_stream",
                                }
                            )
                            return
                        if ev_name == "thinking" and isinstance(data, dict):
                            thinking_parts.append(str(data.get("d") or ""))
                        yield _sse_line(ev_name, data)
                except (httpx.HTTPError, RuntimeError) as exc:
                    err_mark = str(exc)
                    yield _sse_line(
                        "error",
                        build_stream_error_payload(
                            detail=err_mark,
                            code="agent_tools_stream_failed",
                            status=502,
                            phase="agent_tools_stream",
                        ),
                    )
                    write_orchestrator_audit(
                        {
                            "event": "assistant_text_stream_error",
                            "request_id": rid,
                            "intent_summary": intent_preview,
                            "plan": plan.model_dump(),
                            "error": err_mark,
                            "phase": "agent_tools_stream",
                            "turn_not_persisted": True,
                        }
                    )
                    return

                reply = str(meta_holder.get("reply", ""))
                agent_meta_stream = {k: v for k, v in meta_holder.items() if k != "reply"}
            else:
                splitter = RedactedThinkingStreamSplitter()
                reply_parts: list[str] = []
                ndjson_it = iter(
                    iter_ndjson_lines_with_stream_fallback(
                        effective_text,
                        injected_history,
                        primary_profile=router_profile,
                        primary_model_override=model_override,
                        decisions_out=pipeline_decisions,
                    )
                )
                try:
                    while True:
                        if await request.is_disconnected():
                            write_orchestrator_audit(
                                {
                                    "event": "assistant_text_stream_cancelled",
                                    "request_id": rid,
                                    "intent_summary": intent_preview,
                                    "plan": plan.model_dump(),
                                    "phase": "llm_stream",
                                }
                            )
                            return
                        try:
                            line = next(ndjson_it)
                        except StopIteration:
                            break
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        et = ev.get("e")
                        if et == "token":
                            d = str(ev.get("d", ""))
                            full.append(d)
                            for kind, pl in splitter.feed(d):
                                if kind == "thinking":
                                    thinking_parts.append(str(pl.get("d") or ""))
                                    yield _sse_line("thinking", pl)
                                elif kind == "thinking_done":
                                    yield _sse_line("thinking_done", {})
                                elif kind == "token":
                                    reply_parts.append(pl.get("d", ""))
                                    yield _sse_line("token", pl)
                        elif et == "provider":
                            yield _sse_line("provider", {"d": str(ev.get("d", ""))})
                        elif et == "usage":
                            usage_payload = ev.get("d", {})
                            if isinstance(usage_payload, dict):
                                yield _sse_line("usage", usage_payload)
                                pct = usage_payload.get("context_pct")
                                if pct is None and usage_payload.get("total_tokens"):
                                    pct = min(99, int(usage_payload["total_tokens"]) // 10)
                                yield _sse_line(
                                    "token_usage",
                                    {
                                        "in": usage_payload.get("prompt_tokens", 0),
                                        "out": usage_payload.get("completion_tokens", 0),
                                        "pct": pct or 0,
                                    },
                                )
                        elif et == "error":
                            err_mark = str(ev.get("message", "erro no LLM"))
                            yield _sse_line(
                                "error",
                                build_stream_error_payload(
                                    detail=err_mark,
                                    code="llm_stream_error",
                                    status=502,
                                    phase="llm_stream",
                                ),
                            )
                            break
                        elif et == "done":
                            break
                finally:
                    closer = getattr(ndjson_it, "close", None)
                    if callable(closer):
                        closer()
                for kind, pl in splitter.flush():
                    if kind == "thinking":
                        thinking_parts.append(str(pl.get("d") or ""))
                        yield _sse_line("thinking", pl)
                    elif kind == "thinking_done":
                        yield _sse_line("thinking_done", {})
                    elif kind == "token":
                        reply_parts.append(pl.get("d", ""))
                        yield _sse_line("token", pl)
                reply = "".join(reply_parts) if reply_parts else "".join(full)
            plan_dump = plan.model_dump()
            if err_mark:
                write_orchestrator_audit(
                    {
                        "event": "assistant_text_stream_error",
                        "request_id": rid,
                        "intent_summary": intent_preview,
                        "plan": plan_dump,
                        "error": err_mark,
                        "phase": "llm_stream",
                        "turn_not_persisted": True,
                    }
                )
                return
            if not (reply or "").strip():
                empty_detail = "Resposta vazia do modelo; turno não guardado."
                yield _sse_line(
                    "error",
                    build_stream_error_payload(
                        detail=empty_detail,
                        code="empty_reply",
                        status=502,
                        phase="llm_stream",
                    ),
                )
                write_orchestrator_audit(
                    {
                        "event": "assistant_text_stream_error",
                        "request_id": rid,
                        "intent_summary": intent_preview,
                        "plan": plan_dump,
                        "error": empty_detail,
                        "phase": "empty_reply",
                        "turn_not_persisted": True,
                    }
                )
                return
            done_extra: dict[str, Any] = {
                "request_id": rid,
                "schema_version": ASSISTANT_SSE_DONE_SCHEMA_VERSION,
                "reply": reply,
                "plan": plan_dump,
                "ui_trace": stream_ui_trace,
                "pipeline_decisions": pipeline_decisions,
            }
            tier_done = str(prefs_at_stream.get("auto_tier") or "").strip()
            done_extra["composer_segments"] = _build_assistant_composer_segments(
                router_profile=router_profile,
                model_override=str(model_override or ""),
                auto_tier=tier_done,
                perception_modality_role=perception_modality_role,
                perception_model_id=perception_model_id,
                modality_tool_invocations=stream_modality_invocations,
            )
            if stream_modality_invocations:
                done_extra["inference_meta"] = {
                    **inference_meta,
                    "modality_invocations": list(stream_modality_invocations),
                }
            if agent_meta_stream:
                done_extra["agent_tools"] = agent_meta_stream
            if CHAT_SESSIONS_ENABLED and (payload.chat_session_id or "").strip():
                sid_done = (payload.chat_session_id or "").strip()
                try:
                    append_completed_turn(
                        sid_done,
                        user_text=payload.text,
                        assistant_text=reply,
                        active_slot=payload.widget_active_slot,
                    )
                except Exception:
                    pass
                if thinking_parts:
                    try:
                        record_assistant_thinking(
                            session_id=sid_done,
                            tenant_id=resolve_pg_tenant_id(),
                            thinking_text="".join(thinking_parts),
                            slot=payload.widget_active_slot,
                            request_id=rid,
                        )
                    except Exception:
                        pass
            write_orchestrator_audit(
                {
                    "event": "assistant_text_stream_done",
                    "request_id": rid,
                    "intent_summary": intent_preview,
                    "plan": plan_dump,
                    "context_compacted": ctx_stats.compacted,
                    "history_messages_before": ctx_stats.history_messages_before,
                    "history_messages_after": ctx_stats.history_messages_after,
                    "history_chars_before": ctx_stats.history_chars_before,
                    "history_chars_after": ctx_stats.history_chars_after,
                    "reply_chars": len(reply),
                    "memory_enabled": True,
                    "memory_recall_count": recall_count,
                    "pre_injection": bool(PRE_INJECTION_ENABLED),
                    "post_injection_host": inject_host_context,
                    "host_context_from_text_trigger": host_context_trigger_match,
                    "post_injection_memory": bool(payload.include_memory_recall),
                    "post_injection_document_rag": bool(injection_meta.get("document_rag_applied")),
                    "document_rag_chunk_count": int(injection_meta.get("document_rag_chunk_count") or 0),
                    "document_rag_doc_id": injection_meta.get("document_rag_doc_id"),
                    "long_session_memory": payload.include_long_session_memory,
                    "session_truncated": session_truncated,
                    "include_playbook": payload.include_playbook,
                    "include_capability_digest": payload.include_capability_digest,
                    "capability_digest_block_applied": bool(
                        injection_meta.get("capability_digest_block_applied")
                    ),
                    "agent_tools": agent_meta_stream,
                    "pipeline_decisions": pipeline_decisions,
                    "result_ok": True,
                }
            )
            # ── Canvas: extrai HTML da resposta para o LiveCanvas ──
            canvas_html = _extract_canvas_html(reply)
            if canvas_html:
                yield _sse_line("canvas", {"html": canvas_html, "action": "replace"})

            yield _sse_line("done", done_extra)
        except (httpx.HTTPError, RuntimeError) as exc:
            err_s = str(exc)
            write_orchestrator_audit(
                {
                    "event": "assistant_text_stream_error",
                    "request_id": rid,
                    "intent_summary": intent_preview,
                    "plan": plan.model_dump(),
                    "error": err_s,
                    "phase": "http_stream",
                    "turn_not_persisted": True,
                }
            )
            yield _sse_line(
                "error",
                build_stream_error_payload(
                    detail=err_s,
                    code="http_stream_failed",
                    status=502,
                    phase="http_stream",
                ),
            )

    # T4: wrap event_gen with release on stream end/disconnect
    _ev = event_gen()

    async def _guarded_gen():
        stream_ok = True
        try:
            async for event in _ev:
                yield event
        except Exception:
            stream_ok = False
            raise
        finally:
            try:
                from app.shared.business_metrics import stream_finished

                stream_finished(ok=stream_ok)
            except Exception:
                pass
            await _stream_release(stream_tid)

    return StreamingResponse(
        _guarded_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
@router_assistant.post("/assistant/voice", tags=['OpsDashboard'])
async def assistant_voice(
    file: UploadFile = File(...),
    output_filename: str | None = None,
) -> dict[str, Any]:
    if MVP_MODE:
        raise HTTPException(
            status_code=501,
            detail="Voice assistant is disabled in MVP mode. Use POST /assistant/text/stream.",
        )
    _central_focus_abort()
    rid = str(uuid4())
    plan = build_plan_voice_chat(rid)
    _vprefs0 = load_preferences()
    write_orchestrator_audit(
        {
            "event": "assistant_voice_start",
            "request_id": rid,
            "intent_summary": "",
            "plan": plan.model_dump(),
            "default_include_capability_digest": bool(
                _vprefs0.get("default_include_capability_digest")
            ),
            "capability_digest_server_enabled": bool(CAPABILITY_DIGEST_IN_PROMPT_ENABLED),
        }
    )
    try:
        file_bytes = await file.read()
        voice_digest_applied = False
        try:
            transcript = call_stt(
                file_bytes=file_bytes,
                filename=file.filename or "audio.wav",
                content_type=file.content_type or "audio/wav",
            )
        except RuntimeError as exc:
            if str(exc) == "stt_disabled":
                raise HTTPException(status_code=503, detail="STT disabled") from exc
            raise
        if not transcript:
            write_orchestrator_audit(
                {
                    "event": "assistant_voice_done",
                    "request_id": rid,
                    "intent_summary": "",
                    "plan": plan.model_dump(),
                    "result_ok": True,
                    "empty_transcript": True,
                }
            )
            return {
                "request_id": rid,
                "transcript": "",
                "reply": "",
                "audio_file": "",
                "plan": plan.model_dump(),
            }

        _voice_tools_p, voice_router_profile, voice_model_override = resolve_llm_for_assistant_request(payload)
        voice_prefs = load_preferences()
        hist_voice: list[dict[str, str]] = []
        if CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED and not CENTRAL_FOCUS_MODE:
            sp_msgs, _ = build_system_prompt_injection_messages()
            hist_voice.extend(sp_msgs)
        if PRE_INJECTION_ENABLED:
            pre_body = get_pre_injection_body(file_path=PRE_INJECTION_FILE_PATH)
            pre_msg = build_pre_injection_message(pre_body)
            if pre_msg:
                hist_voice.append(pre_msg)
        digest_voice = bool(
            CAPABILITY_DIGEST_IN_PROMPT_ENABLED
            and voice_prefs.get("default_include_capability_digest")
        )
        if digest_voice:
            dg_voice = build_capability_digest_system_message(max_chars=2600)
            if dg_voice:
                hist_voice.append(dg_voice)
                voice_digest_applied = True
                record_capability_digest_injected(
                    "assistant_voice", len(dg_voice.get("content") or "")
                )
        hist_voice.extend(preferences_system_messages(voice_prefs))
        reply = call_llm(
            transcript,
            hist_voice,
            profile=voice_router_profile,
            model_override=voice_model_override,
        )
        audio_file = call_tts(reply, output_filename)
        intent_preview = transcript.strip()[:200]
        write_orchestrator_audit(
            {
                "event": "assistant_voice_done",
                "request_id": rid,
                "intent_summary": intent_preview,
                "plan": plan.model_dump(),
                "result_ok": True,
                "capability_digest_block_applied": voice_digest_applied,
            }
        )
        return {
            "request_id": rid,
            "transcript": transcript,
            "reply": reply,
            "audio_file": audio_file,
            "plan": plan.model_dump(),
        }
    except httpx.HTTPError as exc:
        write_orchestrator_audit(
            {
                "event": "assistant_voice_error",
                "request_id": rid,
                "plan": plan.model_dump(),
                "error": str(exc),
            }
        )
        raise HTTPException(status_code=502, detail=f"Falha no fluxo voice->stt->llm->tts: {exc}") from exc

# ═══ UNDO ENDPOINT ═══


class UndoRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64, description="Request ID of the turn to undo")


class UndoResponse(BaseModel):
    ok: bool
    error: str | None = None
    request_id: str
    files_restored: int = 0
    files_deleted: int = 0
    restored: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)


@router_assistant.post("/assistant/undo")
async def undo_turn_endpoint(body: UndoRequest, request: Request) -> UndoResponse:
    """Revert all file mutations performed during an agent turn."""
    from app.turn_file_log import undo_turn as _undo

    result = _undo(body.request_id)
    resp = UndoResponse(
        ok=result.get("ok", False),
        error=result.get("error"),
        request_id=body.request_id,
        files_restored=result.get("files_restored", 0),
        files_deleted=result.get("files_deleted", 0),
        restored=result.get("restored", []),
        deleted=result.get("deleted", []),
        failed=result.get("failed", []),
    )
    return resp

