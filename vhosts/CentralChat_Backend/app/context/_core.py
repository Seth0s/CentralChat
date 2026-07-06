"""Context domain — types, config, assembler, compaction, sections, session events, projection."""

from __future__ import annotations

from __future__ import annotations
from app.clients import call_llm, fetch_host_summary_best_effort
from app.config import AGENT_TOOLS_RAG_EMBEDDING_BACKEND, CENTRAL_EMBEDDING_BACKEND, CENTRAL_EMBEDDING_DEVICE, CENTRAL_EMBEDDING_MODEL_ID
from app.config import CHAT_SESSIONS_EVENT_LOG_ENABLED
from app.http.problem_details import PROBLEM_TYPE_PREFIX, _title_for_status
from app.inference import resolve_aux_llm_call_params
from app.inference import get_model_router_public_config
from app.playbook import build_playbook_system_message
from app.repositories.preferences_repository import load_preferences
from app.repositories.preferences_repository import load_preferences, preferences_system_messages
# lazy import below
from app.workspace import load_widget_slot_graph
from app.shared.ambientacao import build_capability_digest_system_message, build_post_host_system_message, build_pre_injection_message, get_pre_injection_body, truncate_session_history
from app.shared.ambientacao import truncate_session_history
from app.shared.context_manager import ContextStats
from app.shared.context_manager import ContextStats, load_last_summary, save_last_summary
from app.shared.l8_pipeline_policy import extract_router_caps
from app.shared.multislot_context import apply_multislot_to_compacted_history, build_multislot_system_message, effective_active_slot, first_turn_from_history, graph_neighbors
from app.shared.multislot_context import partition_messages_by_slot
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.prompt_injection import build_document_rag_system_message
from app.shared.prompt_injection import build_eco_summary_prompt
from app.shared.redacted_thinking import assistant_message_for_history
from app.shared.router_extract import slim_injected_history_for_router
from app.shared.system_prompt_loader import build_system_prompt_injection_messages
from app.workspace import normalize_edges
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import dataclass, field
from datetime import datetime
from datetime import datetime, timedelta, timezone
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any
from typing import Any, Callable
from typing import Any, Literal
from typing import Any, Literal, Protocol
from typing import Any, Protocol
from typing import Literal
import app.config as app_config
import json
import logging
import os
import re
import threading
import uuid


# ═══ TYPES ═══

"""Context system domain types (Phase 0 — stable contracts for later phases)."""

class SessionEventType(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    ASSISTANT_THINKING = "assistant_thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CLIENT_JOB_COMPLETED = "client_job_completed"
    CANVAS_PATCH = "canvas_patch"
    TERMINAL_OUTPUT = "terminal_output"
    SUMMARY_UPDATED = "summary_updated"
    RAG_INGEST = "rag_ingest"

class SessionEvent(BaseModel):
    """Single append-only session event (persisted in Phase 2)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    tenant_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=8, max_length=200)
    event_type: SessionEventType = Field(..., validation_alias="type", serialization_alias="type")
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime
    event_id: str | None = Field(default=None, max_length=64)

    @field_validator("payload")
    @classmethod
    def _payload_must_be_mapping(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise TypeError("payload must be a mapping")
        return v

class PromptSectionKind(str, Enum):
    """Ordered prompt sections (see CONTEXT_SYSTEM_SCOPE_AND_ROADMAP §1.5)."""

    SYSTEM_CORE = "system_core"
    SYSTEM_CAPABILITIES = "system_capabilities"
    CONTEXT_RETRIEVED = "context_retrieved"
    CONTEXT_SESSION = "context_session"
    CONTEXT_WORKSPACE = "context_workspace"
    CURRENT_USER = "current_user"

class PromptSection(BaseModel):
    """One logical section before router history is built."""

    model_config = ConfigDict(frozen=True)

    kind: PromptSectionKind
    content: str = ""
    token_count: int | None = Field(default=None, ge=0)
    source: str | None = Field(
        default=None,
        description="Provenance label (e.g. central://core@v1, rag:product)",
    )
    cacheable: bool = False

class TokenAccounting(BaseModel):
    """Token budget snapshot for a single turn."""

    model_config = ConfigDict(frozen=True)

    context_window_cap: int = Field(..., ge=0)
    reserved_output_tokens: int = Field(..., ge=0)
    reserved_injection_tokens: int = Field(..., ge=0)
    compact_threshold_tokens: int = Field(..., ge=0)
    verbatim_tokens: int = Field(default=0, ge=0)
    section_tokens: dict[str, int] = Field(default_factory=dict)
    total_estimated_tokens: int | None = Field(default=None, ge=0)

class PromptPackage(BaseModel):
    """
    Assembled context for one assistant turn.

    `history` is the message list sent to the model-router (after L8 slim in Phase 1).
    """

    model_config = ConfigDict(frozen=True)

    sections: tuple[PromptSection, ...] = ()
    history: tuple[dict[str, str], ...] = ()
    user_text: str = ""
    token_accounting: TokenAccounting | None = None
    injection_meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("history", mode="before")
    @classmethod
    def _coerce_history(cls, v: object) -> tuple[dict[str, str], ...]:
        if v is None:
            return ()
        if isinstance(v, tuple):
            return v
        return tuple(dict(m) for m in v)  # type: ignore[arg-type]

CompactionJobStatus = Literal["pending", "running", "completed", "failed"]

class CompactionJob(BaseModel):
    """Async or sync compaction work unit."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=8, max_length=200)
    status: CompactionJobStatus = "pending"
    covers_event_id_until: str | None = None
    summary_version: int | None = Field(default=None, ge=0)
    verbatim_tokens_before: int = Field(default=0, ge=0)
    verbatim_tokens_after: int | None = Field(default=None, ge=0)
    error: str | None = None


# ═══ CONFIG ═══

"""Context system environment configuration (Phase 0 — no runtime wiring yet)."""

StreamFailurePolicy = Literal["cancel_no_persist"]

_DEFAULT_CAP = 200_000

_DEFAULT_RATIO = 0.75

_DEFAULT_RESERVED_OUTPUT = 16_384

_DEFAULT_EMBEDDING_BACKEND = "local"

_DEFAULT_EMBEDDING_MODEL_ID = "miniLM-L6-v2"

_DEFAULT_RAG_NAMESPACES = ("product", "session", "document")

_DEFAULT_STREAM_POLICY: StreamFailurePolicy = "cancel_no_persist"

_CAP_MIN = 1_000

_CAP_MAX = 1_000_000

_RATIO_MIN = 0.05

_RATIO_MAX = 0.95

_RESERVED_OUTPUT_MAX = 500_000

def _parse_rag_namespaces(raw: str) -> tuple[str, ...]:
    parts = tuple(x.strip() for x in raw.split(",") if x.strip())
    return parts or _DEFAULT_RAG_NAMESPACES

def compute_compact_threshold_tokens(
    *,
    context_window_cap: int,
    reserved_output_tokens: int,
    reserved_injection_tokens: int,
    compact_threshold_ratio: float,
) -> int:
    """Usable verbatim budget trigger: (CAP - output - injection) * ratio."""
    usable = context_window_cap - reserved_output_tokens - reserved_injection_tokens
    if usable <= 0:
        return 0
    return max(0, int(usable * compact_threshold_ratio))

class ContextSystemSettings(BaseModel):
    """Resolved context-system settings for assembler / compaction (Phase 0+)."""

    model_config = ConfigDict(frozen=True)

    context_window_cap: int = Field(default=_DEFAULT_CAP, ge=_CAP_MIN, le=_CAP_MAX)
    compact_threshold_ratio: float = Field(default=_DEFAULT_RATIO, ge=_RATIO_MIN, le=_RATIO_MAX)
    reserved_output_tokens: int = Field(default=_DEFAULT_RESERVED_OUTPUT, ge=0, le=_RESERVED_OUTPUT_MAX)
    reserved_injection_tokens: int = Field(default=0, ge=0, le=_CAP_MAX)
    embedding_backend: str = Field(default=_DEFAULT_EMBEDDING_BACKEND, min_length=1, max_length=32)
    embedding_model_id: str = Field(default=_DEFAULT_EMBEDDING_MODEL_ID, min_length=1, max_length=128)
    rag_namespaces: tuple[str, ...] = Field(default=_DEFAULT_RAG_NAMESPACES)
    rag_tools_only_via_retrieval: bool = True
    stream_failure_policy: StreamFailurePolicy = _DEFAULT_STREAM_POLICY
    memory_enabled: bool = True
    memory_db_url: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def compact_threshold_tokens(self) -> int:
        return compute_compact_threshold_tokens(
            context_window_cap=self.context_window_cap,
            reserved_output_tokens=self.reserved_output_tokens,
            reserved_injection_tokens=self.reserved_injection_tokens,
            compact_threshold_ratio=self.compact_threshold_ratio,
        )

    @field_validator("embedding_backend", mode="before")
    @classmethod
    def _normalize_embedding_backend(cls, v: object) -> str:
        s = str(v or _DEFAULT_EMBEDDING_BACKEND).strip().lower() or _DEFAULT_EMBEDDING_BACKEND
        allowed = {"local", "minilm", "hash"}
        if s not in allowed:
            raise ValueError(f"embedding_backend must be one of {sorted(allowed)}")
        return s

    @field_validator("rag_namespaces", mode="before")
    @classmethod
    def _normalize_rag_namespaces(cls, v: object) -> tuple[str, ...]:
        if isinstance(v, str):
            return _parse_rag_namespaces(v)
        if isinstance(v, (list, tuple)):
            parts = tuple(str(x).strip() for x in v if str(x).strip())
            return parts or _DEFAULT_RAG_NAMESPACES
        return _DEFAULT_RAG_NAMESPACES

    @field_validator("stream_failure_policy", mode="before")
    @classmethod
    def _normalize_stream_policy(cls, v: object) -> str:
        s = str(v or _DEFAULT_STREAM_POLICY).strip().lower() or _DEFAULT_STREAM_POLICY
        if s != "cancel_no_persist":
            raise ValueError("stream_failure_policy must be cancel_no_persist")
        return s

    @model_validator(mode="after")
    def _check_compact_threshold_positive(self) -> ContextSystemSettings:
        if self.compact_threshold_tokens <= 0:
            raise ValueError(
                "compact_threshold_tokens must be positive; "
                "reduce reserved_output_tokens / reserved_injection_tokens or increase context_window_cap"
            )
        return self

def load_context_settings(
    *,
    reserved_injection_tokens: int | None = None,
    environ: dict[str, str] | None = None,
) -> ContextSystemSettings:
    """
    Load settings from environment (CENTRAL_* and related MEMORY_* keys).

    `reserved_injection_tokens` is measured at runtime in later phases; pass explicitly
    when known, otherwise defaults to CENTRAL_RESERVED_INJECTION_TOKENS (0).
    """
    env = environ if environ is not None else os.environ

    def _get(key: str, default: str = "") -> str:
        return env.get(key, default).strip()

    def _get_int(key: str, default: int) -> int:
        raw = _get(key, str(default))
        return int(raw) if raw else default

    def _get_float(key: str, default: float) -> float:
        raw = _get(key, str(default))
        return float(raw) if raw else default

    def _get_bool(key: str, default: bool) -> bool:
        raw = _get(key, "")
        if not raw:
            return default
        return raw.lower() in ("1", "true", "yes", "y")

    cap = _get_int("CENTRAL_CONTEXT_WINDOW_CAP", _DEFAULT_CAP)
    ratio = _get_float("CENTRAL_COMPACT_THRESHOLD_RATIO", _DEFAULT_RATIO)
    reserved_out = _get_int("CENTRAL_RESERVED_OUTPUT_TOKENS", _DEFAULT_RESERVED_OUTPUT)
    reserved_inj_raw = _get("CENTRAL_RESERVED_INJECTION_TOKENS", "0")
    reserved_inj = (
        int(reserved_injection_tokens)
        if reserved_injection_tokens is not None
        else int(reserved_inj_raw or "0")
    )

    return ContextSystemSettings(
        context_window_cap=cap,
        compact_threshold_ratio=ratio,
        reserved_output_tokens=reserved_out,
        reserved_injection_tokens=max(0, reserved_inj),
        embedding_backend=_get("CENTRAL_EMBEDDING_BACKEND", _DEFAULT_EMBEDDING_BACKEND),
        embedding_model_id=_get("CENTRAL_EMBEDDING_MODEL_ID", _DEFAULT_EMBEDDING_MODEL_ID),
        rag_namespaces=_parse_rag_namespaces(
            _get("CENTRAL_RAG_NAMESPACES", ",".join(_DEFAULT_RAG_NAMESPACES))
        ),
        rag_tools_only_via_retrieval=_get_bool("CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", True),
        stream_failure_policy=_get("CENTRAL_STREAM_FAILURE_POLICY", _DEFAULT_STREAM_POLICY),  # type: ignore[arg-type]
        memory_enabled=_get_bool("MEMORY_ENABLED", True),
        memory_db_url=_get(
            "MEMORY_DB_URL",
            "postgresql://central:central@memory-db:5432/central_memory",
        ),
    )


# ═══ TOOL_EVENT_SANITIZE ═══

"""Sanitize tool/job payloads before session event log (ADR-017 phase 5)."""

_DEFAULT_FIELD_CHARS = 2000

_DEFAULT_TOTAL_CHARS = 8000

_LARGE_TEXT_KEYS = frozenset(
    {
        "stdout",
        "stderr",
        "output",
        "preview",
        "raw",
        "content",
        "text",
        "body",
        "data",
    }
)

_BINARY_HINT_KEYS = frozenset({"data", "content_base64", "image", "blob", "bytes"})

def _looks_like_large_binary(value: str) -> bool:
    if len(value) < 512:
        return False
    sample = value[:256]
    if sample.startswith("data:") and ";base64," in sample[:80]:
        return True
    non_printable = sum(1 for c in sample if ord(c) < 9 or (13 < ord(c) < 32))
    return non_printable > len(sample) * 0.15

def _truncate_str(text: str, *, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"

def sanitize_value_for_event_log(
    value: Any,
    *,
    key: str = "",
    max_field_chars: int = _DEFAULT_FIELD_CHARS,
    depth: int = 0,
) -> Any:
    if depth > 6:
        return "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if key in _BINARY_HINT_KEYS and _looks_like_large_binary(value):
            return {"omitted": True, "reason": "binary_or_large_blob", "length": len(value)}
        cap = max_field_chars if key in _LARGE_TEXT_KEYS or len(value) > max_field_chars else max_field_chars
        if len(value) > cap:
            return _truncate_str(value, max_chars=cap)
        return value
    if isinstance(value, list):
        out: list[Any] = []
        for i, item in enumerate(value[:32]):
            out.append(
                sanitize_value_for_event_log(
                    item, key=key, max_field_chars=max_field_chars, depth=depth + 1
                )
            )
        if len(value) > 32:
            out.append({"truncated_list": True, "omitted": len(value) - 32})
        return out
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 48:
                out["_truncated_keys"] = len(value) - 48
                break
            out[str(k)] = sanitize_value_for_event_log(
                v, key=str(k), max_field_chars=max_field_chars, depth=depth + 1
            )
        return out
    return _truncate_str(str(value), max_chars=max_field_chars)

def sanitize_tool_payload_for_event_log(
    payload: dict[str, Any],
    *,
    max_field_chars: int = _DEFAULT_FIELD_CHARS,
    max_total_chars: int = _DEFAULT_TOTAL_CHARS,
) -> dict[str, Any]:
    """Deep-copy sanitize mapping; cap serialized size."""
    cleaned = sanitize_value_for_event_log(
        dict(payload), max_field_chars=max_field_chars, depth=0
    )
    if not isinstance(cleaned, dict):
        return {"sanitized": cleaned}
    try:
        raw = json.dumps(cleaned, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(cleaned)
    if len(raw) <= max_total_chars:
        return cleaned
    return {
        "truncated": True,
        "preview": _truncate_str(raw, max_chars=max_total_chars),
    }

def shell_result_summary(result: dict[str, Any] | None) -> str:
    """One-line summary for transcript / client_job_completed."""
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return f"error={result.get('error')}"
    parts: list[str] = []
    if "exit_code" in result:
        parts.append(f"exit_code={result.get('exit_code')}")
    for key in ("stdout", "stderr"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            excerpt = _truncate_str(val.replace("\n", " "), max_chars=240)
            parts.append(f"{key}={excerpt!r}")
    if result.get("truncated"):
        parts.append("truncated=true")
    return "; ".join(parts)


# ═══ TOOL_TRANSCRIPT ═══

"""Format tool / client-job session events for linear transcript projection."""

_TOOL_SUMMARY_TYPES = frozenset(
    {
        SessionEventType.TOOL_CALL,
        SessionEventType.TOOL_RESULT,
        SessionEventType.CLIENT_JOB_COMPLETED,
    }
)

def tool_summary_message_for_event(ev: SessionEvent) -> dict[str, str] | None:
    """Optional system line for chat history / API projection."""
    if ev.event_type not in _TOOL_SUMMARY_TYPES:
        return None
    p = ev.payload
    if ev.event_type == SessionEventType.TOOL_CALL:
        tool = str(p.get("tool") or p.get("name") or "tool")
        return {"role": "system", "content": f"[tool_call] {tool}"}
    if ev.event_type == SessionEventType.TOOL_RESULT:
        tool = str(p.get("tool") or "tool")
        ok = bool(p.get("ok", True))
        res = p.get("result")
        extra = ""
        if isinstance(res, dict):
            extra = shell_result_summary(res) or str(res.get("status") or res.get("error") or "")[:200]
        elif res is not None:
            extra = str(res)[:200]
        line = f"[tool_result] {tool} ok={ok}"
        if extra:
            line = f"{line}: {extra}"
        return {"role": "system", "content": line[:1200]}
    if ev.event_type == SessionEventType.CLIENT_JOB_COMPLETED:
        action = str(p.get("action_id") or "job")
        status = str(p.get("status") or "")
        summary = str(p.get("summary") or "")
        line = f"[client_job] {action} {status}".strip()
        if summary:
            line = f"{line}: {summary}"
        return {"role": "system", "content": line[:1200]}
    return None


# ═══ TOKEN_BUDGET ═══

"""Token budget estimation (Phase 1 — char heuristic until tokenizer wiring)."""

_CHARS_PER_TOKEN_ESTIMATE = 4

class TokenBudgetAllocator:
    """Estimates token usage for prompt sections and router history."""

    def __init__(self, settings: ContextSystemSettings | None = None) -> None:
        self._settings = settings or load_context_settings()

    @property
    def settings(self) -> ContextSystemSettings:
        return self._settings

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def estimate_messages_tokens(self, messages: list[dict[str, str]]) -> int:
        return sum(self.estimate_tokens(str(m.get("content") or "")) for m in messages)

    def section_tokens_from_messages(
        self,
        sections: tuple[PromptSection, ...],
    ) -> dict[str, int]:
        out: dict[str, int] = {}
        for sec in sections:
            key = sec.kind.value
            count = sec.token_count if sec.token_count is not None else self.estimate_tokens(sec.content)
            out[key] = out.get(key, 0) + count
        return out

    def build_accounting(
        self,
        *,
        prefix_messages: list[dict[str, str]],
        session_messages: list[dict[str, str]],
        sections: tuple[PromptSection, ...],
        injected_history: list[dict[str, str]] | None = None,
    ) -> TokenAccounting:
        section_tokens = self.section_tokens_from_messages(sections)
        verbatim = self.estimate_messages_tokens(session_messages)
        prefix_t = self.estimate_messages_tokens(prefix_messages)
        total_hist = self.estimate_messages_tokens(injected_history or [*prefix_messages, *session_messages])
        reserved_inj = prefix_t
        settings = self._settings.model_copy(update={"reserved_injection_tokens": reserved_inj})
        return TokenAccounting(
            context_window_cap=settings.context_window_cap,
            reserved_output_tokens=settings.reserved_output_tokens,
            reserved_injection_tokens=reserved_inj,
            compact_threshold_tokens=settings.compact_threshold_tokens,
            verbatim_tokens=verbatim,
            section_tokens=section_tokens,
            total_estimated_tokens=total_hist,
        )


# ═══ SESSION_EVENTS ═══

"""Append session events for tools / workspace (Phase 7)."""

_store = None

def _get_store():
    global _store
    if _store is None:
        from app.repositories.session_event_store import SessionEventStore
        _store = SessionEventStore()
    return _store

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _ctx_session_id(ctx: dict[str, Any] | None) -> str | None:
    if not ctx:
        return None
    sid = str(ctx.get("chat_session_id") or "").strip()
    return sid if len(sid) >= 8 else None

def _ctx_tenant(ctx: dict[str, Any] | None) -> str:
    if ctx and str(ctx.get("tenant_id") or "").strip():
        return str(ctx["tenant_id"]).strip()
    return resolve_pg_tenant_id()

def _ctx_slot(ctx: dict[str, Any] | None) -> int:
    if not ctx:
        return 1
    try:
        s = int(ctx.get("active_slot") or ctx.get("default_slot") or 1)
        return max(1, min(4, s))
    except (TypeError, ValueError):
        return 1

def append_session_event(
    *,
    session_id: str,
    tenant_id: str | None,
    event_type: SessionEventType,
    payload: dict[str, Any],
    slot: int | None = None,
) -> SessionEvent | None:
    if not CHAT_SESSIONS_EVENT_LOG_ENABLED:
        return None
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    body = dict(payload)
    if slot is not None and 1 <= int(slot) <= 4:
        body.setdefault("slot", int(slot))
    ev = SessionEvent(
        tenant_id=tid,
        session_id=sid,
        event_type=event_type,
        payload=body,
        ts=_utc_now(),
        event_id=str(uuid.uuid4()),
    )
    return _get_store().append(ev)

def record_assistant_thinking(
    *,
    session_id: str,
    tenant_id: str | None,
    thinking_text: str,
    slot: int | None = None,
    request_id: str | None = None,
) -> SessionEvent | None:
    """H1/D11 — persist redacted CoT digest (not full text in payload)."""
    import hashlib

    text = (thinking_text or "").strip()
    if not text:
        return None
    payload: dict[str, Any] = {
        "redacted": True,
        "chars": len(text),
        "digest": hashlib.sha256(text.encode("utf-8")).hexdigest()[:32],
    }
    if request_id:
        payload["request_id"] = request_id
    ev = append_session_event(
        session_id=session_id,
        tenant_id=tenant_id,
        event_type=SessionEventType.ASSISTANT_THINKING,
        payload=payload,
        slot=slot,
    )
    try:
        from app.audit_service import append_audit_event

        append_audit_event(
            action="session.thinking",
            tenant_id=tenant_id,
            session_id=session_id,
            metadata={"chars": len(text), "digest": payload["digest"], "request_id": request_id},
        )
    except Exception:
        pass
    return ev


def record_tool_invocation(
    *,
    canvas_write_ctx: dict[str, Any] | None,
    tool: str,
    arguments: dict[str, Any],
) -> None:
    sid = _ctx_session_id(canvas_write_ctx)
    if not sid:
        return
    args_excerpt = {k: arguments.get(k) for k in list(arguments.keys())[:12]}
    append_session_event(
        session_id=sid,
        tenant_id=_ctx_tenant(canvas_write_ctx),
        event_type=SessionEventType.TOOL_CALL,
        payload={"tool": tool, "arguments": args_excerpt},
        slot=_ctx_slot(canvas_write_ctx),
    )

def record_tool_result_event(
    *,
    canvas_write_ctx: dict[str, Any] | None,
    tool: str,
    result: dict[str, Any],
) -> None:
    sid = _ctx_session_id(canvas_write_ctx)
    if not sid:
        return
    safe = (
        sanitize_tool_payload_for_event_log(result)
        if isinstance(result, dict)
        else {"raw": sanitize_tool_payload_for_event_log({"value": result}).get("value")}
    )
    ok = not (isinstance(result, dict) and (result.get("error") or result.get("ok") is False))
    append_session_event(
        session_id=sid,
        tenant_id=_ctx_tenant(canvas_write_ctx),
        event_type=SessionEventType.TOOL_RESULT,
        payload={"tool": tool, "ok": bool(ok), "result": safe},
        slot=_ctx_slot(canvas_write_ctx),
    )
    if tool in ("apply_canvas_patch", "manage_workspace_artifact"):
        record_canvas_patch_event(canvas_write_ctx=canvas_write_ctx, result=safe, tool=tool)
    if tool == "request_shell":
        record_terminal_output_event(canvas_write_ctx=canvas_write_ctx, result=safe, tool=tool)

def record_canvas_patch_event(
    *,
    canvas_write_ctx: dict[str, Any] | None,
    result: dict[str, Any],
    tool: str = "apply_canvas_patch",
) -> None:
    sid = _ctx_session_id(canvas_write_ctx)
    if not sid:
        return
    body = sanitize_tool_payload_for_event_log(result) if isinstance(result, dict) else {"raw": result}
    append_session_event(
        session_id=sid,
        tenant_id=_ctx_tenant(canvas_write_ctx),
        event_type=SessionEventType.CANVAS_PATCH,
        payload={"tool": tool, **body},
        slot=_ctx_slot(canvas_write_ctx),
    )

def record_terminal_output_event(
    *,
    canvas_write_ctx: dict[str, Any] | None,
    result: dict[str, Any],
    tool: str = "request_shell",
) -> None:
    sid = _ctx_session_id(canvas_write_ctx)
    if not sid:
        return
    body = sanitize_tool_payload_for_event_log(result) if isinstance(result, dict) else {"raw": result}
    append_session_event(
        session_id=sid,
        tenant_id=_ctx_tenant(canvas_write_ctx),
        event_type=SessionEventType.TERMINAL_OUTPUT,
        payload={"tool": tool, **body},
        slot=_ctx_slot(canvas_write_ctx),
    )

def record_client_job_completed_event(
    *,
    tenant_id: str,
    session_id: str,
    job: dict[str, Any],
    slot: int | None = None,
) -> None:
    """Append ``client_job_completed`` after connector reports final status."""
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return
    status = str(job.get("status") or "")
    result = job.get("result")
    safe_result = sanitize_tool_payload_for_event_log(result) if isinstance(result, dict) else None
    summary = shell_result_summary(safe_result if isinstance(safe_result, dict) else None)
    if not summary and job.get("error_code"):
        summary = f"error_code={job.get('error_code')}"
    append_session_event(
        session_id=sid,
        tenant_id=tenant_id,
        event_type=SessionEventType.CLIENT_JOB_COMPLETED,
        payload={
            "job_id": str(job.get("job_id") or ""),
            "action_id": str(job.get("action_id") or ""),
            "status": status,
            "tool_call_id": job.get("tool_call_id"),
            "error_code": job.get("error_code"),
            "summary": summary,
        },
        slot=slot,
    )

def record_client_job_tool_followups(
    *,
    tenant_id: str,
    session_id: str,
    job: dict[str, Any],
    slot: int | None = None,
) -> None:
    """After async client execution, mirror tool_result (+ terminal for shell)."""
    sid = (session_id or "").strip()
    if len(sid) < 8:
        return
    action_id = str(job.get("action_id") or "")
    status = str(job.get("status") or "")
    result = job.get("result")
    safe = sanitize_tool_payload_for_event_log(result) if isinstance(result, dict) else {}
    ok = status == "succeeded" and not job.get("error_code")
    _action_tool = {
        "shell.exec": "request_shell",
        "file.read": "client_read_file",
        "file.grep": "client_grep",
    }
    tool_name = _action_tool.get(action_id, action_id)
    append_session_event(
        session_id=sid,
        tenant_id=tenant_id,
        event_type=SessionEventType.TOOL_RESULT,
        payload={"tool": tool_name, "ok": bool(ok), "result": safe, "job_id": str(job.get("job_id") or "")},
        slot=slot,
    )
    if action_id == "shell.exec" and isinstance(safe, dict):
        append_session_event(
            session_id=sid,
            tenant_id=tenant_id,
            event_type=SessionEventType.TERMINAL_OUTPUT,
            payload={"tool": tool_name, **safe},
            slot=slot,
        )

def record_client_job_session_events(*, job: dict[str, Any]) -> None:
    """Hook from ``client_jobs_store.submit_job_result`` when ``session_id`` is set."""
    sid = str(job.get("session_id") or "").strip()
    if len(sid) < 8:
        return
    tid = str(job.get("tenant_id") or resolve_pg_tenant_id()).strip()
    record_client_job_completed_event(tenant_id=tid, session_id=sid, job=job)
    if job.get("status") in ("succeeded", "failed"):
        record_client_job_tool_followups(tenant_id=tid, session_id=sid, job=job)


# ═══ SESSION_EVENT_MIGRATION ═══

"""One-shot migration from legacy ``chat_sessions.json`` to event log (Phase 2)."""

def _parse_ts(raw: str | None, *, fallback: datetime) -> datetime:
    if not raw:
        return fallback
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return fallback

def migrate_legacy_chat_sessions(
    *,
    tenant_id: str,
    legacy_root: dict[str, Any],
    store: SessionEventStore | None = None,
) -> int:
    """
    Emit ``user_message`` / ``assistant_message`` events from legacy JSON messages.

    Idempotent: skips sessions that already have any event in the log.
    Returns count of sessions migrated in this run.
    """
    store = store or SessionEventStore()
    existing = store.session_ids_with_events(tenant_id)
    meta = store.load_migration_meta()
    migrated_ids: set[str] = set(meta.get("migrated_session_ids") or [])

    count = 0
    sessions = legacy_root.get("sessions") if isinstance(legacy_root.get("sessions"), list) else []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if len(sid) < 8:
            continue
        if sid in existing or sid in migrated_ids:
            continue
        messages = s.get("messages")
        if not isinstance(messages, list) or not messages:
            migrated_ids.add(sid)
            continue
        base = _parse_ts(str(s.get("updated_at") or ""), fallback=datetime.now(timezone.utc))
        wrote = 0
        for i, row in enumerate(messages):
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "").strip().lower()
            content = str(row.get("content") or "")
            if role not in ("user", "assistant"):
                continue
            ev_type = (
                SessionEventType.USER_MESSAGE
                if role == "user"
                else SessionEventType.ASSISTANT_MESSAGE
            )
            ts = base + timedelta(milliseconds=i)
            store.append(
                SessionEvent(
                    tenant_id=tenant_id,
                    session_id=sid,
                    event_type=ev_type,
                    payload={"content": content},
                    ts=ts,
                    event_id=str(uuid.uuid4()),
                )
            )
            wrote += 1
        if wrote:
            count += 1
        migrated_ids.add(sid)
        existing.add(sid)

    store.save_migration_meta({"schema": 1, "migrated_session_ids": sorted(migrated_ids)})
    return count


# ═══ SESSION_VIEW ═══

"""Session projection for context assembly (Phase 1)."""

@dataclass
class SessionView:
    """
    Conversation messages for assembly.

    When ``messages`` is empty, the assembler builds history from the request payload.
    """

    messages: tuple[dict[str, str], ...] = field(default_factory=tuple)


# ═══ PROJECTION ═══

"""Session event projections (Phase 2)."""

class LinearTranscriptProjection:
    """
    Projects append-only events into UI/API message list (contract §11).

    User/assistant messages plus compact system lines for tool / client-job events.
    """

    _TRANSCRIPT_TYPES = frozenset(
        {
            SessionEventType.USER_MESSAGE,
            SessionEventType.ASSISTANT_MESSAGE,
        }
    )

    def project(self, events: list[SessionEvent]) -> list[dict[str, str]]:
        ordered = sorted(events, key=lambda e: e.ts)
        out: list[dict[str, str]] = []
        for ev in ordered:
            if ev.event_type in self._TRANSCRIPT_TYPES:
                role = "user" if ev.event_type == SessionEventType.USER_MESSAGE else "assistant"
                content = str(ev.payload.get("content") or "")
                out.append({"role": role, "content": content})
                continue
            summary = tool_summary_message_for_event(ev)
            if summary:
                out.append(summary)
        return out


# ═══ EMBEDDING_SERVICE ═══

"""Local embedding service (Phase 3 — VPS CPU only for retrieval)."""

EmbeddingProfile = Literal["memory", "tools"]

MEMORY_HASH_DIM = 256

TOOLS_VECTOR_DIM = 384

MINILM_MODEL_ID = "sentence_transformers_all_minilm_l6_v2"

HASH_MODEL_ID_MEMORY = "local_hash_v1"

HASH_MODEL_ID_TOOLS = "local_hash_384_v1"

class EmbeddingService(Protocol):
    def embed_memory(self, text: str) -> tuple[list[float], str]: ...

    def embed_tools(self, text: str) -> tuple[list[float], str]: ...

_ST_MODEL: Any = None

def _encode_minilm(text: str) -> list[float]:
    global _ST_MODEL
    if _ST_MODEL is None:
        from sentence_transformers import SentenceTransformer

        dev = "cuda" if CENTRAL_EMBEDDING_DEVICE in ("cuda", "gpu") else "cpu"
        model_name = CENTRAL_EMBEDDING_MODEL_ID
        if model_name.lower() in ("minilm-l6-v2", "minilm"):
            model_name = "sentence-transformers/all-MiniLM-L6-v2"
        elif "/" not in model_name:
            model_name = "sentence-transformers/all-MiniLM-L6-v2"
        _ST_MODEL = SentenceTransformer(model_name, device=dev)
    vec = _ST_MODEL.encode(
        (text or "").strip() or " ",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [float(x) for x in vec]

class LocalEmbeddingService:
    """CPU embeddings: memory profile (hash 256d); tools profile (MiniLM or hash 384d)."""

    def embed_memory(self, text: str) -> tuple[list[float], str]:
        from app.rag import embed_local_hash

        return embed_local_hash(text or "", dim=MEMORY_HASH_DIM), HASH_MODEL_ID_MEMORY

    def embed_tools(self, text: str) -> tuple[list[float], str]:
        from app.rag import embed_local_hash

        backend = (CENTRAL_EMBEDDING_BACKEND or "local").strip().lower()
        tools_backend = AGENT_TOOLS_RAG_EMBEDDING_BACKEND
        use_hash = backend == "hash" or tools_backend == "hash"
        if use_hash:
            return embed_local_hash(text or "", dim=TOOLS_VECTOR_DIM), HASH_MODEL_ID_TOOLS
        if backend in ("local", "minilm") or tools_backend == "minilm":
            try:
                return _encode_minilm(text), MINILM_MODEL_ID
            except Exception:
                return embed_local_hash(text or "", dim=TOOLS_VECTOR_DIM), HASH_MODEL_ID_TOOLS
        return embed_local_hash(text or "", dim=TOOLS_VECTOR_DIM), HASH_MODEL_ID_TOOLS

_default_service = LocalEmbeddingService()

def get_embedding_service() -> EmbeddingService:
    return _default_service


# ═══ GRAPH_PROJECTION ═══

"""Context graph projection from session event log (Phase 7 — G3)."""

_SLOT_PREFIX_RE = re.compile(r"^slot:([1-4]):\s*", re.IGNORECASE)

GraphNodeKind = Literal["slot", "message", "canvas", "terminal", "tool_call", "tool_result"]

GraphEdgeKind = Literal["slot_link", "belongs_to_slot", "follows", "workspace_on_slot"]

@dataclass
class GraphNode:
    node_id: str
    kind: GraphNodeKind
    slot: int | None = None
    event_id: str | None = None
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class GraphEdge:
    kind: GraphEdgeKind
    source: str
    target: str
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkspaceSnippet:
    """Compact workspace signal for prompt (canvas / terminal)."""

    kind: Literal["canvas_patch", "terminal_output"]
    slot: int
    event_id: str
    excerpt: str
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class ContextGraph:
    """Projected G3 graph: slot topology + per-slot messages + workspace nodes."""

    schema_version: int = 1
    widget_slot_graph_version: int = 0
    slot_edges: list[dict[str, int]] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    messages_by_slot: dict[int, list[dict[str, str]]] = field(default_factory=dict)
    workspace_snippets: list[WorkspaceSnippet] = field(default_factory=list)
    transcript_flat: list[dict[str, str]] = field(default_factory=list)
    rebuilt_from_events: int = 0

    def as_slot_graph_dict(self) -> dict[str, Any]:
        return {"version": int(self.widget_slot_graph_version), "edges": list(self.slot_edges)}

    def transcript_messages(self) -> list[dict[str, str]]:
        """Chronological transcript with ``slot:N:`` prefixes (multislot input)."""
        return list(self.transcript_flat)

    def audit_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "widget_slot_graph_version": self.widget_slot_graph_version,
            "slot_edge_count": len(self.slot_edges),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "rebuilt_from_events": self.rebuilt_from_events,
            "slots_with_messages": sorted(self.messages_by_slot.keys()),
            "workspace_snippet_count": len(self.workspace_snippets),
        }

def _slot_node_id(slot: int) -> str:
    return f"slot:{slot}"

def _event_node_id(event_id: str) -> str:
    return f"evt:{event_id}"

def _resolve_slot_from_event(ev: SessionEvent, *, default_slot: int) -> int:
    raw = ev.payload.get("slot")
    if raw is not None:
        try:
            s = int(raw)
            if 1 <= s <= 4:
                return s
        except (TypeError, ValueError):
            pass
    content = str(ev.payload.get("content") or "")
    mo = _SLOT_PREFIX_RE.match(content)
    if mo:
        return int(mo.group(1))
    return max(1, min(4, int(default_slot)))

def _strip_slot_prefix(content: str) -> str:
    mo = _SLOT_PREFIX_RE.match(content or "")
    if mo:
        return content[mo.end() :].lstrip()
    return content

def _excerpt(payload: dict[str, Any], *, max_chars: int = 400) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"

class ContextGraphProjection:
    """
    Rebuilds a context graph from append-only events + persisted widget slot topology.

    Slot edges come from ``widget_slot_graph.json`` (SSOT). Message and workspace nodes
    are derived only from the event log (rebuildable).
    """

    _TRANSCRIPT_TYPES = frozenset(
        {
            SessionEventType.USER_MESSAGE,
            SessionEventType.ASSISTANT_MESSAGE,
        }
    )

    def rebuild(
        self,
        events: list[SessionEvent],
        *,
        slot_graph: dict[str, Any] | None,
        default_slot: int = 1,
    ) -> ContextGraph:
        ordered = sorted(events, key=lambda e: e.ts)
        sg = slot_graph or {}
        try:
            version = int(sg.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        edges_raw = sg.get("edges") if isinstance(sg.get("edges"), list) else []
        slot_edges = normalize_edges(edges_raw)

        graph = ContextGraph(
            widget_slot_graph_version=max(0, version),
            slot_edges=slot_edges,
            rebuilt_from_events=len(ordered),
        )

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        for s in range(1, 5):
            nid = _slot_node_id(s)
            nodes.append(GraphNode(node_id=nid, kind="slot", slot=s, label=f"Slot {s}"))
        for e in slot_edges:
            a = int(e["slot_a"])
            b = int(e["slot_b"])
            edges.append(
                GraphEdge(
                    kind="slot_link",
                    source=_slot_node_id(a),
                    target=_slot_node_id(b),
                    meta={"symmetric": True},
                )
            )

        buckets: dict[int, list[dict[str, str]]] = {1: [], 2: [], 3: [], 4: []}
        transcript_flat: list[dict[str, str]] = []
        prev_msg_node: str | None = None
        workspace: list[WorkspaceSnippet] = []

        for ev in ordered:
            eid = str(ev.event_id or "")
            slot = _resolve_slot_from_event(ev, default_slot=default_slot)

            if ev.event_type in self._TRANSCRIPT_TYPES:
                role = "user" if ev.event_type == SessionEventType.USER_MESSAGE else "assistant"
                content = _strip_slot_prefix(str(ev.payload.get("content") or ""))
                buckets[slot].append({"role": role, "content": content})
                transcript_flat.append({"role": role, "content": f"slot:{slot}: {content}"})
                if eid:
                    mid = _event_node_id(eid)
                    nodes.append(
                        GraphNode(
                            node_id=mid,
                            kind="message",
                            slot=slot,
                            event_id=eid,
                            label=role,
                            meta={"role": role},
                        )
                    )
                    edges.append(
                        GraphEdge(
                            kind="belongs_to_slot",
                            source=mid,
                            target=_slot_node_id(slot),
                        )
                    )
                    if prev_msg_node:
                        edges.append(
                            GraphEdge(kind="follows", source=prev_msg_node, target=mid)
                        )
                    prev_msg_node = mid
                continue

            summary = tool_summary_message_for_event(ev)
            if summary:
                transcript_flat.append(summary)

            if ev.event_type == SessionEventType.TOOL_CALL and eid:
                mid = _event_node_id(eid)
                tool = str(ev.payload.get("tool") or "")
                nodes.append(
                    GraphNode(
                        node_id=mid,
                        kind="tool_call",
                        slot=slot,
                        event_id=eid,
                        label=tool,
                        meta={"tool": tool},
                    )
                )
                edges.append(
                    GraphEdge(kind="belongs_to_slot", source=mid, target=_slot_node_id(slot))
                )
                continue

            if ev.event_type == SessionEventType.TOOL_RESULT and eid:
                mid = _event_node_id(eid)
                tool = str(ev.payload.get("tool") or "")
                nodes.append(
                    GraphNode(
                        node_id=mid,
                        kind="tool_result",
                        slot=slot,
                        event_id=eid,
                        label=tool,
                        meta={"ok": bool(ev.payload.get("ok", True))},
                    )
                )
                edges.append(
                    GraphEdge(kind="belongs_to_slot", source=mid, target=_slot_node_id(slot))
                )
                continue

            if ev.event_type == SessionEventType.CANVAS_PATCH and eid:
                mid = _event_node_id(eid)
                nodes.append(
                    GraphNode(
                        node_id=mid,
                        kind="canvas",
                        slot=slot,
                        event_id=eid,
                        label="canvas",
                    )
                )
                edges.append(
                    GraphEdge(kind="workspace_on_slot", source=mid, target=_slot_node_id(slot))
                )
                workspace.append(
                    WorkspaceSnippet(
                        kind="canvas_patch",
                        slot=slot,
                        event_id=eid,
                        excerpt=_excerpt(ev.payload),
                        meta=dict(ev.payload),
                    )
                )
                continue

            if ev.event_type == SessionEventType.TERMINAL_OUTPUT and eid:
                mid = _event_node_id(eid)
                nodes.append(
                    GraphNode(
                        node_id=mid,
                        kind="terminal",
                        slot=slot,
                        event_id=eid,
                        label="terminal",
                    )
                )
                edges.append(
                    GraphEdge(kind="workspace_on_slot", source=mid, target=_slot_node_id(slot))
                )
                workspace.append(
                    WorkspaceSnippet(
                        kind="terminal_output",
                        slot=slot,
                        event_id=eid,
                        excerpt=_excerpt(ev.payload),
                        meta=dict(ev.payload),
                    )
                )

        graph.nodes = nodes
        graph.edges = edges
        graph.messages_by_slot = {k: v for k, v in buckets.items() if v}
        graph.transcript_flat = transcript_flat
        graph.workspace_snippets = workspace[-12:]
        return graph

    def transcript_from_events(
        self,
        events: list[SessionEvent],
        *,
        slot_graph: dict[str, Any] | None,
        default_slot: int = 1,
    ) -> list[dict[str, str]]:
        return self.rebuild(events, slot_graph=slot_graph, default_slot=default_slot).transcript_messages()

    def partition_from_graph(
        self,
        graph: ContextGraph,
        *,
        default_slot: int,
    ) -> dict[int, list[dict[str, str]]]:
        if graph.messages_by_slot:
            out: dict[int, list[dict[str, str]]] = {1: [], 2: [], 3: [], 4: []}
            for s, msgs in graph.messages_by_slot.items():
                if 1 <= int(s) <= 4:
                    out[int(s)] = list(msgs)
            return out
        return partition_messages_by_slot(graph.transcript_messages(), default_slot)

def build_workspace_context_message(
    snippets: list[WorkspaceSnippet],
    *,
    active_slot: int,
    max_chars: int = 2400,
) -> dict[str, str] | None:
    """Optional system block: recent canvas/terminal events on active slot (+ neighbors)."""
    if not snippets:
        return None
    lines = [
        "[CONTEXT_WORKSPACE — graph projection; canvas/terminal excerpts only]",
        f"active_slot: {active_slot}",
    ]
    used = len(lines[0])
    for sn in reversed(snippets):
        if sn.slot != active_slot:
            continue
        block = f"\n--- {sn.kind} slot={sn.slot} event={sn.event_id[:8]} ---\n{sn.excerpt}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    body = "\n".join(lines).strip()
    if len(body) < 48:
        return None
    return {"role": "system", "content": body}


# ═══ COMPACTION_SERVICE ═══

"""CompactionService — token-triggered rolling summaries (Phase 6)."""

_log = logging.getLogger(__name__)

_SUMMARY_PREFIX = "Memory summary (compacted history):\n"

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="context-compact")

_PENDING: set[tuple[str, str]] = set()

_PENDING_LOCK = threading.Lock()

@dataclass
class CompactionResult:
    compacted_history: list[dict[str, str]]
    ctx_stats: ContextStats
    summary: str | None
    compaction_meta: dict[str, Any]

def _is_summary_message(msg: dict[str, str]) -> bool:
    if str(msg.get("role") or "").strip() != "system":
        return False
    content = str(msg.get("content") or "")
    return content.startswith(_SUMMARY_PREFIX) or content.startswith("Memory summary")

def _summary_message(text: str) -> dict[str, str]:
    return {"role": "system", "content": _SUMMARY_PREFIX + text.strip()}

def _estimate_tokens(history: list[dict[str, str]], allocator: TokenBudgetAllocator) -> int:
    return allocator.estimate_messages_tokens(history)

def _split_tail_min_tokens(
    history: list[dict[str, str]],
    *,
    min_verbatim_tokens: int,
    allocator: TokenBudgetAllocator,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep tail with at least ``min_verbatim_tokens``; return (older, recent)."""
    if not history:
        return [], []
    kept: list[dict[str, str]] = []
    total = 0
    for msg in reversed(history):
        kept.insert(0, msg)
        total += allocator.estimate_tokens(str(msg.get("content") or ""))
        if total >= min_verbatim_tokens:
            break
    if len(kept) >= len(history):
        return [], list(history)
    older = history[: len(history) - len(kept)]
    return older, kept

def _last_event_id(tenant_id: str, session_id: str) -> str | None:
    try:
        events = SessionEventStore().list_for_session(tenant_id, session_id)
        if not events:
            return None
        return str(events[-1].event_id or "") or None
    except Exception:
        return None

def _load_stored_summary(
    *,
    tenant_id: str,
    session_id: str | None,
    summary_store_path: str,
) -> tuple[str | None, int | None, str | None]:
    if session_id and len(session_id.strip()) >= 8:
        from app.sessions import get_latest_session_summary

        row = get_latest_session_summary(tenant_id=tenant_id, session_id=session_id.strip())
        if row and row.summary_text.strip():
            return row.summary_text.strip(), row.version, row.provenance
    legacy = load_last_summary(summary_store_path)
    if legacy:
        return legacy.strip(), None, "file_legacy"
    return None, None, None

def _persist_summary(
    *,
    tenant_id: str,
    session_id: str | None,
    summary: str,
    request_id: str,
    provenance: str,
    summary_store_path: str,
    covers_event_id_until: str | None,
) -> int | None:
    save_last_summary(summary_store_path, summary, request_id=request_id, provenance=provenance)
    if session_id and len(session_id.strip()) >= 8:
        from app.sessions import insert_session_summary

        row = insert_session_summary(
            tenant_id=tenant_id,
            session_id=session_id.strip(),
            summary_text=summary,
            covers_event_id_until=covers_event_id_until,
            request_id=request_id,
            provenance=provenance,
        )
        if row:
            return row.version
    return None

def _schedule_async_compaction(
    *,
    tenant_id: str,
    session_id: str,
    older: list[dict[str, str]],
    request_id: str,
    summarizer: Callable[[list[dict[str, str]]], str],
    summary_store_path: str,
    provenance: str,
) -> bool:
    if not app_config.CENTRAL_COMPACTION_ASYNC_ENABLED:
        return False
    key = (tenant_id, session_id)
    with _PENDING_LOCK:
        if key in _PENDING:
            return False
        _PENDING.add(key)

    def _work() -> None:
        try:
            if not older:
                return
            summary = str(summarizer(older)).strip()
            if not summary:
                return
            covers = _last_event_id(tenant_id, session_id)
            _persist_summary(
                tenant_id=tenant_id,
                session_id=session_id,
                summary=summary,
                request_id=request_id,
                provenance=provenance,
                summary_store_path=summary_store_path,
                covers_event_id_until=covers,
            )
        except Exception as exc:
            _log.debug("async_compaction_failed session=%s err=%s", session_id, exc)
        finally:
            with _PENDING_LOCK:
                _PENDING.discard(key)

    _EXECUTOR.submit(_work)
    return True

class CompactionService:
    """Token-budget compaction with optional async eco summarization."""

    def __init__(
        self,
        *,
        settings: ContextSystemSettings | None = None,
        token_allocator: TokenBudgetAllocator | None = None,
    ) -> None:
        self._settings = settings or load_context_settings()
        self._allocator = token_allocator or TokenBudgetAllocator(self._settings)

    def compact(
        self,
        *,
        history: list[dict[str, str]],
        request_id: str,
        session_id: str | None,
        tenant_id: str | None,
        eco_summarizer: Callable[[list[dict[str, str]]], str],
        include_long_session_memory: bool,
        session_max_messages: int,
        summary_store_path: str,
        summary_provenance: str = "eco_summarizer",
    ) -> CompactionResult:
        tid = (tenant_id or resolve_pg_tenant_id()).strip()
        sid = (session_id or "").strip() or None
        before_msgs = len(history)
        verbatim_before = _estimate_tokens(history, self._allocator)
        meta: dict[str, Any] = {
            "compaction_applied": False,
            "compaction_mode": "none",
            "summary_version": None,
            "verbatim_tokens_before": verbatim_before,
            "verbatim_tokens_after": verbatim_before,
            "compact_threshold_tokens": self._settings.compact_threshold_tokens,
            "async_scheduled": False,
        }

        if not include_long_session_memory:
            compacted, truncated = truncate_session_history(history, max_messages=session_max_messages)
            after_tokens = _estimate_tokens(compacted, self._allocator)
            meta["compaction_mode"] = "truncated" if truncated else "none"
            meta["verbatim_tokens_after"] = after_tokens
            stats = ContextStats(
                history_messages_before=before_msgs,
                history_messages_after=len(compacted),
                history_chars_before=sum(len(m.get("content") or "") for m in history),
                history_chars_after=sum(len(m.get("content") or "") for m in compacted),
                compacted=False,
                summary_chars=0,
                summary_provenance=None,
                summary_version=None,
                verbatim_tokens_before=verbatim_before,
                verbatim_tokens_after=after_tokens,
                compaction_mode=str(meta["compaction_mode"]),
            )
            return CompactionResult(
                compacted_history=compacted,
                ctx_stats=stats,
                summary=None,
                compaction_meta=meta,
            )

        threshold = self._settings.compact_threshold_tokens
        min_verbatim = max(0, app_config.CENTRAL_COMPACT_MIN_VERBATIM_TOKENS)
        cap = self._settings.context_window_cap
        sync_overflow = verbatim_before >= int(cap * app_config.CENTRAL_COMPACTION_SYNC_OVERFLOW_RATIO)

        if verbatim_before <= threshold:
            stats = ContextStats(
                history_messages_before=before_msgs,
                history_messages_after=before_msgs,
                history_chars_before=sum(len(m.get("content") or "") for m in history),
                history_chars_after=sum(len(m.get("content") or "") for m in history),
                compacted=False,
                summary_chars=0,
                summary_provenance=None,
                summary_version=None,
                verbatim_tokens_before=verbatim_before,
                verbatim_tokens_after=verbatim_before,
                compaction_mode="none",
            )
            return CompactionResult(
                compacted_history=list(history),
                ctx_stats=stats,
                summary=None,
                compaction_meta=meta,
            )

        older, recent = _split_tail_min_tokens(
            history,
            min_verbatim_tokens=min_verbatim,
            allocator=self._allocator,
        )
        if not older:
            stats = ContextStats(
                history_messages_before=before_msgs,
                history_messages_after=before_msgs,
                history_chars_before=sum(len(m.get("content") or "") for m in history),
                history_chars_after=sum(len(m.get("content") or "") for m in history),
                compacted=False,
                summary_chars=0,
                summary_provenance=None,
                summary_version=None,
                verbatim_tokens_before=verbatim_before,
                verbatim_tokens_after=verbatim_before,
                compaction_mode="below_min_split",
            )
            meta["compaction_mode"] = "below_min_split"
            return CompactionResult(
                compacted_history=list(history),
                ctx_stats=stats,
                summary=None,
                compaction_meta=meta,
            )

        stored_summary, stored_version, stored_prov = _load_stored_summary(
            tenant_id=tid,
            session_id=sid,
            summary_store_path=summary_store_path,
        )
        summary = stored_summary
        summary_version = stored_version
        prov = summary_provenance
        mode = "cached_summary"

        if sync_overflow and older:
            try:
                fresh = str(eco_summarizer(older)).strip() or None
            except Exception:
                fresh = None
            if fresh:
                summary = fresh
                covers = _last_event_id(tid, sid) if sid else None
                summary_version = _persist_summary(
                    tenant_id=tid,
                    session_id=sid,
                    summary=summary,
                    request_id=request_id,
                    provenance=summary_provenance,
                    summary_store_path=summary_store_path,
                    covers_event_id_until=covers,
                )
                mode = "sync"
        elif sid and older:
            scheduled = _schedule_async_compaction(
                tenant_id=tid,
                session_id=sid,
                older=older,
                request_id=request_id,
                summarizer=eco_summarizer,
                summary_store_path=summary_store_path,
                provenance=summary_provenance,
            )
            meta["async_scheduled"] = scheduled
            mode = "async_pending" if scheduled else "cached_summary"

        new_history = list(recent)
        if summary:
            new_history = [_summary_message(summary), *recent]

        verbatim_after = _estimate_tokens(recent, self._allocator)
        meta.update(
            {
                "compaction_applied": True,
                "compaction_mode": mode,
                "summary_version": summary_version,
                "verbatim_tokens_after": verbatim_after,
                "sync_overflow": sync_overflow,
            }
        )

        stats = ContextStats(
            history_messages_before=before_msgs,
            history_messages_after=len(new_history),
            history_chars_before=sum(len(m.get("content") or "") for m in history),
            history_chars_after=sum(len(m.get("content") or "") for m in new_history),
            compacted=True,
            summary_chars=len(summary or ""),
            summary_provenance=prov if summary else None,
            summary_version=summary_version,
            verbatim_tokens_before=verbatim_before,
            verbatim_tokens_after=verbatim_after,
            compaction_mode=mode,
        )
        try:
            from app.shared.context_metrics import record_compaction_run

            record_compaction_run(mode=mode)
        except Exception:
            pass
        return CompactionResult(
            compacted_history=new_history,
            ctx_stats=stats,
            summary=summary,
            compaction_meta=meta,
        )

_default_compaction_service = CompactionService()

# ═══ STREAM_ERRORS ═══

"""SSE stream errors aligned with RFC 9457 Problem Details (Phase 8 / D8)."""

TURN_NOT_PERSISTED_PT = "Este turno não foi guardado na sessão."

def build_stream_error_payload(
    *,
    detail: str,
    code: str = "stream_failed",
    status: int = 502,
    phase: str | None = None,
    turn_not_persisted: bool = True,
) -> dict[str, Any]:
    """
    Payload for SSE event ``error``.

    Includes Problem Details fields plus UI hints (``turn_not_persisted``, ``user_message_pt``).
    Keeps ``message`` for backward-compatible clients.
    """
    title = _title_for_status(status)
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_PREFIX}/{code}",
        "title": title,
        "status": int(status),
        "detail": (detail or title).strip()[:2000],
        "message": (detail or title).strip()[:2000],
        "code": code,
        "turn_not_persisted": bool(turn_not_persisted),
    }
    if turn_not_persisted:
        body["user_message_pt"] = TURN_NOT_PERSISTED_PT
    if phase:
        body["phase"] = phase
    return body

