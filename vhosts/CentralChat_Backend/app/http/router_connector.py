"""ADR-017 phase 2 — connector register, heartbeat, job poll, result."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.connector import (
    client_jobs_db_enabled,
    fetch_and_claim_jobs_for_connector,
    submit_job_result,
)
from app.config import CENTRAL_CLIENT_JOBS_ENABLED, CENTRAL_CONNECTOR_AUTH_MODE
from app.connector import heartbeat_connector, register_connector, sanitize_connector_id
from app.shared.pg_tenant import resolve_pg_tenant_id

router_connector = APIRouter(tags=["Connector"])


class ConnectorRegisterRequest(BaseModel):
    connector_id: str = Field(..., min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=list)
    protocol_version: str = Field(default="1", max_length=16)
    device_label: str | None = Field(default=None, max_length=256)


class ConnectorHeartbeatRequest(BaseModel):
    connector_id: str = Field(..., min_length=1, max_length=128)


class ConnectorJobResultRequest(BaseModel):
    status: Literal["succeeded", "failed"]
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=128)
    connector_id: str | None = Field(default=None, max_length=128)


def _require_client_jobs() -> None:
    if not CENTRAL_CLIENT_JOBS_ENABLED:
        raise HTTPException(status_code=503, detail="client_jobs_disabled")
    if not client_jobs_db_enabled():
        raise HTTPException(
            status_code=503,
            detail="client_jobs_db_unavailable",
        )


def _tenant_from_jwt() -> str:
    """
    Connector API is scoped to the JWT ``client_id`` (CENTRAL_CONNECTOR_AUTH_MODE=jwt).

    Tenant context is set by auth middleware before the handler runs.
    """
    if CENTRAL_CONNECTOR_AUTH_MODE not in ("jwt", ""):
        raise HTTPException(status_code=501, detail="connector_auth_mode_not_supported")
    return resolve_pg_tenant_id()


@router_connector.post("/connector/register")
def connector_register(payload: ConnectorRegisterRequest) -> dict[str, Any]:
    _require_client_jobs()
    tid = _tenant_from_jwt()
    try:
        sanitize_connector_id(payload.connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_connector_id") from exc
    try:
        return register_connector(
            tenant_id=tid,
            connector_id=payload.connector_id,
            capabilities=payload.capabilities,
            protocol_version=payload.protocol_version,
            device_label=payload.device_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router_connector.post("/connector/heartbeat")
def connector_heartbeat(payload: ConnectorHeartbeatRequest) -> dict[str, Any]:
    _require_client_jobs()
    tid = _tenant_from_jwt()
    try:
        out = heartbeat_connector(tenant_id=tid, connector_id=payload.connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_connector_id") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not out:
        raise HTTPException(status_code=404, detail="connector_not_registered")
    return out


@router_connector.get("/connector/jobs")
def connector_poll_jobs(
    connector_id: str = Query(..., max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """
    Long-poll MVP: jobs assigned by the dispatcher (``dispatched`` → ``running``).

    WebSocket push is not implemented in this phase; connectors poll this endpoint.
    """
    _require_client_jobs()
    tid = _tenant_from_jwt()
    try:
        cid = sanitize_connector_id(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_connector_id") from exc
    jobs = fetch_and_claim_jobs_for_connector(
        tenant_id=tid,
        connector_id=cid,
        limit=limit,
    )
    return {
        "items": jobs,
        "tenant_id": tid,
        "transport": "poll",
        "protocol_version": "1",
    }


@router_connector.post("/connector/jobs/{job_id}/result")
def connector_job_result(job_id: str, payload: ConnectorJobResultRequest) -> dict[str, Any]:
    _require_client_jobs()
    tid = _tenant_from_jwt()
    cid = None
    if payload.connector_id:
        try:
            cid = sanitize_connector_id(payload.connector_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_connector_id") from exc
    try:
        job = submit_job_result(
            tenant_id=tid,
            job_id=job_id,
            status=payload.status,
            result=payload.result,
            error_code=payload.error_code,
            connector_id=cid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found_or_not_runnable")
    return job


# T13 — inference_complete: connector reports inference result to VPS

class InferenceCompleteRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)
    reply: str = Field(default="")
    model: str = Field(default="unknown")
    usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = Field(None, max_length=500)
    chat_session_id: str | None = Field(None, max_length=128)


@router_connector.post("/connector/inference-complete", tags=["Connector"])
def inference_complete(payload: InferenceCompleteRequest) -> dict[str, Any]:
    """Connector reports inference result. VPS persists audit, updates quota."""
    from app.shared.orchestrator_audit import write_event
    from app.tenant_quota import increment_usage

    tid = resolve_pg_tenant_id()

    if payload.error:
        write_event(
            {
                "event": "connector_inference_error",
                "request_id": payload.request_id,
                "error": payload.error,
                "tenant_id": tid,
            }
        )
        return {"ok": True, "persisted": False, "error": payload.error}

    # Update quota from usage data
    if payload.usage:
        pt = int(payload.usage.get("prompt_tokens", 0))
        ct = int(payload.usage.get("completion_tokens", 0))
        if pt or ct:
            try:
                increment_usage(tid, tokens_input=pt, tokens_output=ct)
            except Exception:
                pass

    write_event(
        {
            "event": "connector_inference_complete",
            "request_id": payload.request_id,
            "model": payload.model,
            "tenant_id": tid,
            "reply_len": len(payload.reply),
        }
    )

    return {"ok": True, "persisted": True}


# ── Phase 3: Connector workspace context ──

class ConnectorContextPush(BaseModel):
    """Connector pushes a workspace context snapshot to the backend."""
    connector_id: str = Field(..., min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=64)
    repo_structure: str = Field(default="", max_length=64_000)
    active_file: str | None = Field(default=None, max_length=4096)
    git_branch: str | None = Field(default=None, max_length=256)
    git_dirty: bool = False
    recent_changes: str = Field(default="", max_length=16_000)
    open_files: list[str] = Field(default_factory=list)


# In-memory context cache: connector_id → latest snapshot
_connector_contexts: dict[str, dict[str, Any]] = {}


@router_connector.put("/connector/{connector_id}/context")
def connector_push_context(connector_id: str, payload: ConnectorContextPush) -> dict[str, Any]:
    """Connector pushes workspace context snapshot. Stored in-memory, consumed by ContextPipeline L2."""
    _require_client_jobs()
    tid = _tenant_from_jwt()
    try:
        cid = sanitize_connector_id(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_connector_id") from exc

    _connector_contexts[cid] = {
        "connector_id": cid,
        "workspace_id": payload.workspace_id,
        "repo_structure": payload.repo_structure,
        "active_file": payload.active_file,
        "git_branch": payload.git_branch,
        "git_dirty": payload.git_dirty,
        "recent_changes": payload.recent_changes,
        "open_files": payload.open_files,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tid,
    }
    return {"ok": True, "connector_id": cid, "stored": True}


@router_connector.get("/connector/{connector_id}/context")
def connector_get_context(connector_id: str) -> dict[str, Any]:
    """Retrieve latest context snapshot for a connector (debug)."""
    try:
        cid = sanitize_connector_id(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_connector_id") from exc
    ctx = _connector_contexts.get(cid)
    if not ctx:
        return {"connector_id": cid, "found": False}
    return {"connector_id": cid, "found": True, "context": ctx}


def get_connector_context(connector_id: str) -> dict[str, Any] | None:
    """Return latest context snapshot for a connector (used by ContextPipeline)."""
    return _connector_contexts.get(sanitize_connector_id(connector_id) if connector_id else "")
