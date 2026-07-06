"""T12 — User Context Sync endpoint (POST /connector/context-sync).

Receives context blobs from the connector, diffs them, and caches.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.shared.user_context_cache import sync_user_context, context_cache_stats
from app.shared.pg_tenant import resolve_pg_tenant_id

router_context_sync = APIRouter()


class ContextSyncPayload(BaseModel):
    identity: dict[str, Any] | None = None
    agents: list[dict[str, Any]] | None = None
    skills: list[dict[str, Any]] | None = None
    tools: list[dict[str, Any]] | None = None
    client_version: str | None = Field(None, max_length=64)


@router_context_sync.post("/connector/context-sync", tags=["Connector"])
def connector_context_sync(payload: ContextSyncPayload) -> dict[str, Any]:
    """
    Receive context sync from connector.
    Returns diff summary with what changed.
    """
    tid = resolve_pg_tenant_id()
    result = sync_user_context(
        tid,
        identity=payload.identity,
        agents=payload.agents,
        skills=payload.skills,
        tools=payload.tools,
    )
    if payload.client_version:
        result["client_version"] = payload.client_version
    return result


@router_context_sync.get("/connector/context-cache", tags=["Connector"])
def connector_context_cache_info() -> dict[str, Any]:
    """Debug: view cached context state."""
    return context_cache_stats()
