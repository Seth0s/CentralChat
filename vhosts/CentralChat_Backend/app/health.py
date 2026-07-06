"""Health, metrics, and host summary endpoints."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Response
from prometheus_client import generate_latest

try:
    from prometheus_client import CONTENT_TYPE_LATEST
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

from app.clients import (
    call_kernel_observer_audit_summary,
    call_kernel_observer_snapshot,
    call_system_agent_summary,
    fetch_host_summary_best_effort,
)
from app.config import KERNEL_OBSERVER_URL, PROMETHEUS_URL, SYSTEM_AGENT_URL
from app.workspace import maybe_refresh_workspace_metrics

# ═══ ROUTERS ═══

router_well_known = APIRouter()
router_host = APIRouter()


# ═══ HEALTH ═══

@router_well_known.get("/health", tags=["WellKnown"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router_well_known.get("/health/ready", tags=["WellKnown"])
def health_ready() -> dict[str, Any]:
    """A3.1 — liveness + Postgres when memory DB is enabled."""
    out: dict[str, Any] = {"status": "ok", "checks": {}}
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            out["checks"]["postgres"] = {"status": "disabled"}
            return out
        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        out["checks"]["postgres"] = {"status": "ok"}
    except Exception as exc:
        out["status"] = "degraded"
        out["checks"]["postgres"] = {"status": "error", "detail": str(exc)[:200]}
    return out


# ═══ METRICS ═══

@router_well_known.get("/metrics", tags=["WellKnown"])
def metrics() -> Response:
    maybe_refresh_workspace_metrics()
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        from app.shared.business_metrics import refresh_siem_dead_gauge

        if memory_db_enabled():
            with connect_pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM siem_outbox WHERE status='dead'")
                row = cur.fetchone()
                refresh_siem_dead_gauge(int(row[0] or 0) if row else 0)
    except Exception:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ═══ SERVICE HEALTH (helper) ═══

def _service_health(url: str) -> dict[str, str]:
    if not url:
        return {"status": "disabled"}
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(f"{url}/health")
            response.raise_for_status()
        return {"status": "ok"}
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": str(exc)}


# ═══ PROMETHEUS QUERY (helper) ═══

def _query_prometheus(query: str) -> list[dict]:
    with httpx.Client(timeout=8) as client:
        response = client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result", [])


# ═══ HOST SUMMARY ═══

def _host_summary_payload(rid: str) -> dict[str, Any]:
    """Agregado host; falha de system-agent propaga (para GET /host/summary)."""
    system_agent = call_system_agent_summary(rid)
    kernel_observer: dict | None = None
    kernel_observer_error: str | None = None
    try:
        kernel_observer = call_kernel_observer_snapshot(rid)
    except httpx.HTTPError as exc:
        kernel_observer_error = str(exc)
    kernel_audit: dict | None = None
    kernel_audit_error: str | None = None
    try:
        kernel_audit = call_kernel_observer_audit_summary(rid)
    except httpx.HTTPError as exc:
        kernel_audit_error = str(exc)
    return {
        "request_id": rid,
        "system_agent": system_agent,
        "kernel_observer": kernel_observer,
        "kernel_observer_error": kernel_observer_error,
        "kernel_audit": kernel_audit,
        "kernel_audit_error": kernel_audit_error,
    }


def _host_summary_payload_best_effort(rid: str) -> dict[str, Any]:
    """Para pos-injecao: nunca levanta; erros embutidos no JSON."""
    return fetch_host_summary_best_effort(rid)


@router_host.get("/host/summary", tags=["OpsDashboard"])
def host_summary(request_id: str | None = None) -> dict:
    from app.server import _central_focus_abort

    _central_focus_abort()
    rid = request_id or str(uuid4())
    try:
        return _host_summary_payload(rid)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar system-agent: {exc}") from exc
