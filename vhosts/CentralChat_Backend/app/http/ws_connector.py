"""WebSocket connector — TEAM hybrid mode transport layer.

wss://{api}/connector/v1/ws — single persistent connection replacing HTTP poll.

Message types (from CLI_RUNTIME_MODES.md §4.4):
  CLI→VPS: assistant_turn, tool_result, turn_complete, heartbeat, context_push
  VPS→CLI: inference_plan, approval_required, policy_denied, ping

Design doc: docs/CLI_RUNTIME_MODES.md §4.4, TEAM-2
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router_ws = APIRouter(tags=["TEAM"])

# Active connections: connector_id → WebSocket
_active_connections: dict[str, WebSocket] = {}

# Session → connector mapping
_session_connectors: dict[str, str] = {}

# Connector context store (L2 push + exposed_root)
_connector_contexts: dict[str, dict[str, Any]] = {}

# Track which tools require approval for which session (T3.5)
_pending_approvals: dict[str, list[str]] = {}  # request_id → [tool_names]

# Gzip threshold: plans larger than this get compressed (T5.3)
_GZIP_THRESHOLD_BYTES = 10_000


# ═══════════════════════════════════════════════════════════════
# Message types (Pydantic for validation)
# ═══════════════════════════════════════════════════════════════

class AssistantTurnMessage(BaseModel):
    """CLI → VPS: new user turn."""
    msg_type: str = Field(default="assistant_turn", alias="type")
    request_id: str
    text: str
    chat_session_id: str | None = None
    work_item_id: str | None = None
    agent_name: str | None = None
    model_override: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    context_version: int | None = None


class ToolResultMessage(BaseModel):
    """CLI → VPS: result of a tool execution."""
    msg_type: str = Field(default="tool_result", alias="type")
    request_id: str
    tool_name: str
    tool_call_id: str
    result: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    success: bool = True
    error: str | None = None


class TurnCompleteMessage(BaseModel):
    """CLI → VPS: end of turn with usage stats."""
    msg_type: str = Field(default="turn_complete", alias="type")
    request_id: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reply_hash: str | None = None
    tools_used: list[dict[str, Any]] = Field(default_factory=list)
    first_token_ms: int | None = None
    total_duration_ms: int = 0
    status: str = "completed"


class HeartbeatMessage(BaseModel):
    """CLI → VPS: keepalive."""
    msg_type: str = Field(default="heartbeat", alias="type")
    connector_id: str
    timestamp: float = Field(default_factory=time.time)


class ContextPushMessage(BaseModel):
    """CLI → VPS: L2 context update (git branch, active file, exposed_root)."""
    msg_type: str = Field(default="context_push", alias="type")
    connector_id: str
    git_branch: str | None = None
    git_dirty: bool = False
    active_file: str | None = None
    workspace_path: str | None = None
    exposed_root: str | None = None
    """Root directory exposed by the connector. All file paths must be within this (T3.3)."""


# ═══════════════════════════════════════════════════════════════
# WebSocket endpoint
# ═══════════════════════════════════════════════════════════════

@router_ws.websocket("/connector/v1/ws")
async def ws_connector(websocket: WebSocket) -> None:
    """WebSocket endpoint for TEAM hybrid mode.

    Single persistent connection per CLI instance.
    Handles all message types from CLI_RUNTIME_MODES.md §4.4.
    """
    await websocket.accept()
    connector_id: str | None = None

    try:
        # First message must be a heartbeat or turn with connector_id
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "heartbeat":
                connector_id = msg.get("connector_id", "")
                if connector_id:
                    _active_connections[connector_id] = websocket
                    logger.info("WS connected: connector_id=%s", connector_id)
                    await _send_json(websocket, {
                        "type": "welcome",
                        "connector_id": connector_id,
                        "message": "Connected to CentralChat TEAM",
                    })
                continue

            if msg_type == "assistant_turn":
                await _handle_assistant_turn(websocket, msg, connector_id)
                continue

            if msg_type == "tool_result":
                await _handle_tool_result(websocket, msg, connector_id)
                continue

            if msg_type == "turn_complete":
                await _handle_turn_complete(websocket, msg, connector_id)
                continue

            if msg_type == "context_push":
                await _handle_context_push(websocket, msg, connector_id)
                continue

            # Unknown message type
            await _send_json(websocket, {
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            })

    except WebSocketDisconnect:
        logger.info("WS disconnected: connector_id=%s", connector_id)
    except Exception:
        logger.exception("WS error: connector_id=%s", connector_id)
    finally:
        if connector_id and connector_id in _active_connections:
            del _active_connections[connector_id]
        # Clean session mapping
        to_remove = [k for k, v in _session_connectors.items() if v == connector_id]
        for k in to_remove:
            del _session_connectors[k]


# ═══════════════════════════════════════════════════════════════
# Message handlers
# ═══════════════════════════════════════════════════════════════

async def _handle_assistant_turn(
    websocket: WebSocket, msg: dict, connector_id: str | None,
) -> None:
    """Handle a new turn: assemble context, return InferencePlan."""
    from app.context_engine import assemble_context_sync
    from app.inference_plan import (
        build_inference_plan, get_context_version, bump_context_version,
    )

    request_id = msg.get("request_id", "")
    user_text = msg.get("text", "")
    session_id = msg.get("chat_session_id")

    if not user_text:
        await _send_json(websocket, {
            "type": "policy_denied",
            "request_id": request_id,
            "reason": "Empty text",
        })
        return

    # Map session to connector for fast path
    if session_id and connector_id:
        _session_connectors[session_id] = connector_id

    # T3.1: context version tracking for delta optimization
    cli_version = msg.get("context_version", 0)
    current_version = get_context_version(session_id)

    try:
        state = assemble_context_sync(
            request_id=request_id,
            user_text=user_text,
            history=msg.get("history", []),
            tenant_id="default",
            session_id=session_id,
            work_item_id=msg.get("work_item_id"),
            agent_name=msg.get("agent_name"),
            mode="cli",
            connector_alive=True,
            connector_id=connector_id,
            workspace_path=msg.get("workspace_path"),
        )

        model_id = msg.get("model_override") or "openai/gpt-4o-mini"
        plan = build_inference_plan(
            state,
            request_id=request_id,
            chat_session_id=session_id,
            work_item_id=msg.get("work_item_id"),
            model_id=model_id,
            context_version=cli_version if cli_version > 0 else None,
        )

        # T3.1: bump version after building plan
        new_version = bump_context_version(session_id)

        # T3.5: mark tools that require approval
        approval_tools = plan.policy_digest.requires_approval_for
        if approval_tools:
            tool_names_needing_approval = [
                t["function"]["name"] for t in plan.tools
                if any(at in t["function"]["name"] for at in approval_tools)
            ]
            if tool_names_needing_approval:
                _pending_approvals[request_id] = tool_names_needing_approval

        response = {
            "type": "inference_plan",
            "plan": json.loads(plan.model_dump_json(by_alias=True)),
            "context_version": new_version,
            "approval_required_for": _pending_approvals.get(request_id, []),
        }

        await _send_json(websocket, response)

    except Exception as e:
        logger.exception("Turn assembly failed")
        await _send_json(websocket, {
            "type": "policy_denied",
            "request_id": request_id,
            "reason": f"Context assembly failed: {e}",
        })


async def _handle_tool_result(
    websocket: WebSocket, msg: dict, connector_id: str | None,
) -> None:
    """Handle a tool result from the CLI, with SHA256 stale check (T3.4)."""
    request_id = msg.get("request_id", "")
    tool_name = msg.get("tool_name", "")
    result = msg.get("result", {})

    # T3.4: SHA256 stale diff check for file reads
    if tool_name == "read_file" and result.get("sha256"):
        file_path = result.get("path", "")
        current_sha = result["sha256"]
        from app.onda5_hardening import check_stale_diff, record_file_read

        if file_path and current_sha:
            is_stale = check_stale_diff(request_id, file_path, current_sha)
            if is_stale:
                await _send_json(websocket, {
                    "type": "stale_diff_warning",
                    "request_id": request_id,
                    "file_path": file_path,
                    "message": "File changed since last read. Re-read before applying patch.",
                })
            else:
                record_file_read(request_id, file_path, current_sha)

    # T3.5: Clear pending approval for this tool
    if request_id in _pending_approvals:
        _pending_approvals[request_id] = [
            t for t in _pending_approvals[request_id] if t != tool_name
        ]
        if not _pending_approvals[request_id]:
            del _pending_approvals[request_id]

    logger.info(
        "tool_result request_id=%s tool=%s success=%s duration_ms=%s",
        request_id, tool_name,
        msg.get("success", True), msg.get("duration_ms", 0),
    )

    await _send_json(websocket, {
        "type": "tool_result_ack",
        "request_id": request_id,
        "tool_name": tool_name,
        "status": "recorded",
    })


async def _handle_turn_complete(
    websocket: WebSocket, msg: dict, connector_id: str | None,
) -> None:
    """Handle turn completion with usage stats."""
    request_id = msg.get("request_id", "")

    logger.info(
        "turn_complete request_id=%s model=%s tokens=%d/%d first_token_ms=%s",
        request_id,
        msg.get("model_id"), msg.get("prompt_tokens"), msg.get("completion_tokens"),
        msg.get("first_token_ms"),
    )

    # Persist usage report
    try:
        from app.connector_inference_routes import _reports, InferenceReport
        import uuid
        from datetime import datetime, timezone

        report = InferenceReport(
            id=str(uuid.uuid4()),
            request_id=request_id,
            model_id=msg.get("model_id", "unknown"),
            prompt_tokens=msg.get("prompt_tokens", 0),
            completion_tokens=msg.get("completion_tokens", 0),
            total_tokens=msg.get("total_tokens", 0),
            reply_hash_sha256=msg.get("reply_hash"),
            total_duration_ms=msg.get("total_duration_ms", 0),
            status=msg.get("status", "completed"),
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _reports[report.id] = report
    except Exception:
        logger.debug("Usage report persist failed", exc_info=True)

    await _send_json(websocket, {
        "type": "turn_complete_ack",
        "request_id": request_id,
        "status": "recorded",
    })


async def _handle_context_push(
    websocket: WebSocket, msg: dict, connector_id: str | None,
) -> None:
    """Handle L2 context push (git branch, active file)."""
    logger.debug(
        "context_push connector_id=%s branch=%s file=%s",
        connector_id,
        msg.get("git_branch"), msg.get("active_file"),
    )

    # Update connector context for future turns (in-memory store)
    if connector_id:
        try:
            ctx = _connector_contexts.get(connector_id, {})
            ctx.update({
                "git_branch": msg.get("git_branch"),
                "git_dirty": msg.get("git_dirty", False),
                "active_file": msg.get("active_file"),
                "workspace_path": msg.get("workspace_path"),
            })
            # T3.3: exposed_root for path validation
            if msg.get("exposed_root"):
                exposed = msg["exposed_root"]
                ctx["exposed_root"] = exposed
                # Validate workspace_path is within exposed_root
                ws = msg.get("workspace_path", "")
                if ws and not ws.startswith(exposed):
                    await _send_json(websocket, {
                        "type": "policy_denied",
                        "request_id": msg.get("request_id", ""),
                        "reason": f"workspace_path '{ws}' is outside exposed_root '{exposed}'",
                    })
                    return
            _connector_contexts[connector_id] = ctx
        except Exception:
            logger.debug("Context push update failed", exc_info=True)

    await _send_json(websocket, {
        "type": "context_push_ack",
        "connector_id": connector_id,
        "status": "received",
    })


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

async def _send_json(websocket: WebSocket, data: dict, *, compress: bool = True) -> None:
    """Send JSON over WebSocket, with optional gzip compression for large payloads (T5.3)."""
    text = json.dumps(data, default=str)
    if compress and len(text.encode()) > _GZIP_THRESHOLD_BYTES:
        compressed = gzip.compress(text.encode())
        await websocket.send_bytes(compressed)
        logger.debug("WS sent gzip: %d → %d bytes", len(text), len(compressed))
    else:
        await websocket.send_text(text)


def is_session_local(session_id: str, connector_id: str) -> bool:
    """Check if a session is running on the same connector (fast path eligible)."""
    return _session_connectors.get(session_id) == connector_id


def get_connector_ws(connector_id: str) -> WebSocket | None:
    """Get the active WebSocket for a connector."""
    return _active_connections.get(connector_id)
