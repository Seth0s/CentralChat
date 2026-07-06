"""Connector inference routes — TEAM mode usage reporting.

POST /connector/inference-complete  — CLI reports usage after local inference
GET  /connector/inference-history  — Query past inference reports

Design doc: docs/CLI_RUNTIME_MODES.md §4.2 (step 9), TEAM-1 T1.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router_connector_inference = APIRouter(prefix="/connector", tags=["TEAM"])


# ═══════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════

class ToolUsage(BaseModel):
    """Summary of a tool call during local inference."""

    tool_name: str
    call_count: int = 1
    total_duration_ms: int = 0
    success: bool = True
    error: str | None = None


class InferenceCompleteRequest(BaseModel):
    """Report from CLI after local inference completes.

    Sent at the end of each turn in TEAM hybrid mode.
    The VPS uses this for audit, quota tracking, and session indexing.
    """

    request_id: str = Field(..., description="Matches the InferencePlan.request_id")
    chat_session_id: str | None = None
    work_item_id: str | None = None

    # Model usage
    model_id: str = Field(..., description="Actual model used (must match plan)")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    # Response
    reply_length_chars: int = Field(default=0, ge=0)
    reply_hash_sha256: str | None = None

    # Tool usage
    tools_used: list[ToolUsage] = Field(default_factory=list)
    total_tool_calls: int = Field(default=0, ge=0)

    # Timing
    first_token_ms: int | None = None  # Time to first token (performance metric)
    total_duration_ms: int = Field(default=0, ge=0)

    # Status
    status: str = Field(default="completed", description="completed | aborted | error")
    error_message: str | None = None

    # Tenant context
    tenant_id: str = Field(default="default")
    connector_id: str | None = None


class InferenceReport(BaseModel):
    """Stored inference report."""

    id: str
    request_id: str
    chat_session_id: str | None = None
    work_item_id: str | None = None
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reply_hash_sha256: str | None = None
    tools_used: list[ToolUsage] = []
    first_token_ms: int | None = None
    total_duration_ms: int
    status: str
    tenant_id: str
    created_at: str


# ═══════════════════════════════════════════════════════════════
# In-memory store (PG-backed in production)
# ═══════════════════════════════════════════════════════════════

_reports: dict[str, InferenceReport] = {}


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@router_connector_inference.post("/inference-complete", status_code=200)
async def report_inference_complete(req: InferenceCompleteRequest) -> dict[str, Any]:
    """Report inference completion from the CLI.

    Called after each turn in TEAM hybrid mode.
    The CLI sends this after the LLM finishes streaming tokens locally.
    VPS uses this for:
    - Audit trail (token usage, model compliance)
    - Quota tracking
    - Session indexing triggers
    - Performance metrics (first_token_ms)
    """
    import uuid

    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    report = InferenceReport(
        id=report_id,
        request_id=req.request_id,
        chat_session_id=req.chat_session_id,
        work_item_id=req.work_item_id,
        model_id=req.model_id,
        prompt_tokens=req.prompt_tokens,
        completion_tokens=req.completion_tokens,
        total_tokens=req.total_tokens,
        reply_hash_sha256=req.reply_hash_sha256,
        tools_used=req.tools_used,
        first_token_ms=req.first_token_ms,
        total_duration_ms=req.total_duration_ms,
        status=req.status,
        tenant_id=req.tenant_id,
        created_at=now,
    )

    _reports[report_id] = report

    # Log key metrics
    logger.info(
        "inference_complete request_id=%s model=%s tokens=%d/%d tools=%d first_token_ms=%s duration_ms=%d",
        req.request_id, req.model_id,
        req.prompt_tokens, req.completion_tokens,
        len(req.tools_used), req.first_token_ms, req.total_duration_ms,
    )

    # Try PG persist
    try:
        _pg_persist_report(report)
    except Exception:
        logger.debug("PG persist failed for inference report", exc_info=True)

    return {
        "ok": True,
        "report_id": report_id,
        "message": "Inference report received",
    }


@router_connector_inference.get("/inference-history")
async def get_inference_history(
    chat_session_id: str | None = Query(default=None),
    work_item_id: str | None = Query(default=None),
    tenant_id: str = Query(default="default"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Query past inference reports."""
    items = [
        r for r in _reports.values()
        if r.tenant_id == tenant_id
        and (not chat_session_id or r.chat_session_id == chat_session_id)
        and (not work_item_id or r.work_item_id == work_item_id)
    ]
    items.sort(key=lambda r: r.created_at, reverse=True)
    return {
        "items": items[:limit],
        "total": len(items),
    }


# ═══════════════════════════════════════════════════════════════
# PG persist (best-effort)
# ═══════════════════════════════════════════════════════════════

def _pg_persist_report(report: InferenceReport) -> None:
    """Persist inference report to PG (best-effort)."""
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            return

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS inference_reports (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    chat_session_id TEXT,
                    work_item_id TEXT,
                    model_id TEXT NOT NULL,
                    prompt_tokens INT DEFAULT 0,
                    completion_tokens INT DEFAULT 0,
                    total_tokens INT DEFAULT 0,
                    reply_hash_sha256 TEXT,
                    tools_used JSONB DEFAULT '[]',
                    first_token_ms INT,
                    total_duration_ms INT DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    tenant_id TEXT DEFAULT 'default',
                    created_at TIMESTAMPTZ DEFAULT now()
                );"""
            )
            import json

            cur.execute(
                """INSERT INTO inference_reports
                   (id, request_id, chat_session_id, work_item_id, model_id,
                    prompt_tokens, completion_tokens, total_tokens,
                    reply_hash_sha256, tools_used, first_token_ms,
                    total_duration_ms, status, tenant_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    report.id, report.request_id,
                    report.chat_session_id, report.work_item_id,
                    report.model_id,
                    report.prompt_tokens, report.completion_tokens, report.total_tokens,
                    report.reply_hash_sha256,
                    json.dumps([t.model_dump() for t in report.tools_used], default=str),
                    report.first_token_ms, report.total_duration_ms,
                    report.status, report.tenant_id,
                    report.created_at,
                ),
            )
    except Exception:
        pass  # Best-effort
