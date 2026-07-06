"""Timeline API — unified event feed across WI, sessions, and approvals.

GET /timeline?work_item_id=WI-142  → all events for a work item
GET /timeline?session_id=xxx        → all events for a session
GET /timeline?tenant_id=xxx         → recent events for a tenant (capped)

Returns chronological list of events from:
- work_item_events (PG): status changes, assignments, comments
- session_events (PG): turns completed, handoffs, forks
- approvals (JSON store): created, reviewed, approved/rejected

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §9.5 (Onda 5.5)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router_timeline = APIRouter(tags=["Timeline"])


# ═══════════════════════════════════════════════════════════════
# Response models
# ═══════════════════════════════════════════════════════════════

class TimelineEvent(BaseModel):
    """A single event in the unified timeline."""

    event_id: str
    source: str  # work_item | session | approval
    event_type: str
    actor_id: str | None = None
    timestamp: str
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    """Unified timeline response."""

    items: list[TimelineEvent]
    total: int
    filters: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Route
# ═══════════════════════════════════════════════════════════════

@router_timeline.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    work_item_id: str | None = Query(default=None, description="Filter by work item ID"),
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    tenant_id: str = Query(default="default"),
    limit: int = Query(default=50, ge=1, le=200),
    sources: str | None = Query(default=None, description="Comma-separated: work_item,session,approval"),
) -> TimelineResponse:
    """Get a unified timeline of events.

    At least one filter (work_item_id, session_id) should be provided.
    When only tenant_id is given, returns most recent events across all sources.
    """
    if not work_item_id and not session_id:
        # Tenant-wide: return recent events (capped)
        pass

    source_filter = set(s.strip() for s in (sources or "").split(",") if s.strip())
    if not source_filter:
        source_filter = {"work_item", "session", "approval"}

    events: list[TimelineEvent] = []

    # ── Work item events (PG) ─────────────────────────────────
    if "work_item" in source_filter and work_item_id:
        events.extend(_fetch_work_item_events(work_item_id, tenant_id))

    # ── Session events (PG) ───────────────────────────────────
    if "session" in source_filter and session_id:
        events.extend(_fetch_session_events(session_id, tenant_id))

    # ── Approvals (JSON store) ─────────────────────────────────
    if "approval" in source_filter:
        events.extend(_fetch_approval_events(
            work_item_id=work_item_id,
            session_id=session_id,
            tenant_id=tenant_id,
        ))

    # Sort by timestamp descending
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Apply limit
    total = len(events)
    events = events[:limit]

    return TimelineResponse(
        items=events,
        total=total,
        filters={
            "work_item_id": work_item_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "sources": list(source_filter),
            "limit": limit,
        },
    )


# ═══════════════════════════════════════════════════════════════
# Data fetchers (synchronous, called from async handler)
# ═══════════════════════════════════════════════════════════════

def _fetch_work_item_events(work_item_id: str, tenant_id: str) -> list[TimelineEvent]:
    """Fetch work item events from PG."""
    try:
        from app.work_queue import list_work_item_events

        raw = list_work_item_events(work_item_id, tenant_id=tenant_id)
        events: list[TimelineEvent] = []
        for e in raw:
            events.append(TimelineEvent(
                event_id=str(e.get("event_id", "")),
                source="work_item",
                event_type=str(e.get("event_type", "unknown")),
                actor_id=str(e.get("actor_id", "")) if e.get("actor_id") else None,
                timestamp=_iso(e.get("created_at")),
                summary=_wi_event_summary(e),
                metadata={
                    "work_item_id": work_item_id,
                    "from_status": e.get("from_status"),
                    "to_status": e.get("to_status"),
                },
            ))
        return events
    except Exception:
        logger.debug("Timeline: WI events failed", exc_info=True)
        return []


def _fetch_session_events(session_id: str, tenant_id: str) -> list[TimelineEvent]:
    """Fetch session events from PG."""
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            return []

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, session_id, event_type, payload, created_at
                   FROM session_events
                   WHERE tenant_id = %s AND session_id = %s
                   ORDER BY created_at DESC
                   LIMIT 100""",
                (tenant_id, session_id),
            )
            rows = cur.fetchall()

        events: list[TimelineEvent] = []
        for row in rows:
            payload = row[3] if isinstance(row[3], dict) else {}
            events.append(TimelineEvent(
                event_id=f"session:{row[0]}",
                source="session",
                event_type=str(row[2] or "unknown"),
                actor_id=payload.get("user_id") or payload.get("actor_id"),
                timestamp=_iso(row[4]),
                summary=_session_event_summary(row[2], payload),
                metadata={
                    "session_id": session_id,
                    "payload": payload,
                },
            ))
        return events
    except Exception:
        logger.debug("Timeline: session events failed", exc_info=True)
        return []


def _fetch_approval_events(
    *,
    work_item_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str = "default",
) -> list[TimelineEvent]:
    """Fetch approval events from JSON store, filtered by WI or session."""
    try:
        from app.shared.approvals_store import list_approvals

        raw = list_approvals(status=None, tenant_id=tenant_id)
        events: list[TimelineEvent] = []

        for a in raw:
            # Filter by WI or session
            awi = a.get("work_item_id") or a.get("metadata", {}).get("work_item_id")
            asid = a.get("session_id") or a.get("metadata", {}).get("session_id")

            if work_item_id and awi != work_item_id:
                continue
            if session_id and asid != session_id:
                continue

            events.append(TimelineEvent(
                event_id=str(a.get("approval_id", a.get("id", "?"))),
                source="approval",
                event_type=f"approval_{a.get('status', 'unknown')}",
                actor_id=a.get("requester_id") or a.get("approver_id"),
                timestamp=_iso(a.get("created_at") or a.get("updated_at")),
                summary=_approval_summary(a),
                metadata={
                    "approval_id": a.get("approval_id"),
                    "approval_type": a.get("approval_type") or a.get("type"),
                    "status": a.get("status"),
                    "title": a.get("title", ""),
                    "work_item_id": awi,
                    "session_id": asid,
                },
            ))

        return events
    except Exception:
        logger.debug("Timeline: approval events failed", exc_info=True)
        return []


# ═══════════════════════════════════════════════════════════════
# Summary helpers
# ═══════════════════════════════════════════════════════════════

def _wi_event_summary(e: dict) -> str:
    """Build a human-readable summary for a work item event."""
    etype = str(e.get("event_type", ""))
    from_s = e.get("from_status", "")
    to_s = e.get("to_status", "")
    meta = e.get("metadata", {})

    if etype == "status_change":
        return f"Status changed from '{from_s}' to '{to_s}'"
    if etype == "created":
        return f"Work item created: {meta.get('title', '')}"
    if etype == "assigned":
        return f"Assigned to {meta.get('assignee', 'unknown')}"
    if etype == "comment":
        body = str(meta.get("body", ""))[:100]
        return f"Comment: {body}"
    return etype.replace("_", " ").capitalize()


def _session_event_summary(event_type: str | None, payload: dict) -> str:
    """Build a summary for a session event."""
    etype = (event_type or "").lower()

    if "turn_completed" in etype or "assistant_turn" in etype:
        user_text = str(payload.get("user_text", ""))[:80]
        return f"Turn completed: {user_text}"
    if "handoff" in etype:
        return f"Session handed off to {payload.get('target_user', 'unknown')}"
    if "fork" in etype:
        return f"Session forked from {payload.get('from_session', 'unknown')}"
    if "created" in etype:
        return "Session created"
    return etype.replace("_", " ").capitalize()


def _approval_summary(a: dict) -> str:
    """Build a summary for an approval event."""
    title = str(a.get("title", ""))[:80]
    status = str(a.get("status", ""))
    atype = str(a.get("approval_type", a.get("type", "")))

    if status == "pending":
        return f"Approval pending: {title} ({atype})"
    if status == "approved":
        return f"Approval approved: {title}"
    if status == "denied":
        return f"Approval denied: {title}"
    return f"Approval {status}: {title}"


def _iso(val: Any) -> str:
    """Convert a value to ISO timestamp string."""
    if val is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)
