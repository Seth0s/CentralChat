"""InferencePlan — VPS → CLI contract for TEAM hybrid inference.

The VPS assembles context (ContextEngine) but does NOT call the LLM.
Instead it returns an InferencePlan that the CLI uses to call the
LLM locally (OpenRouter/Ollama). The VPS only sees the plan, not tokens.

Design doc: docs/CLI_RUNTIME_MODES.md §4.2–4.3
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Pydantic schemas
# ═══════════════════════════════════════════════════════════════

class ModelSpec(BaseModel):
    """LLM model specification for the CLI to use."""

    model_id: str = Field(..., description="Provider model ID (e.g. openai/gpt-4o-mini)")
    profile: str = Field(default="balanced", description="Inference profile")
    max_tokens: int = Field(default=8192, ge=1, le=200000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class PolicyDigest(BaseModel):
    """Compact policy summary for the CLI to enforce locally."""

    sha256: str = Field(..., description="Hash of the full policy for integrity check")
    allowed_write_paths: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    requires_approval_for: list[str] = Field(default_factory=list)
    dlp_enabled: bool = True
    focus_mode: bool = False
    role: str = "developer"


class ContextMeta(BaseModel):
    """Metadata about what context layers were applied."""

    layers: list[str] = Field(default_factory=list)
    ui_trace_summary_pt: str = ""
    build_ms: float = 0.0
    session_truncated: bool = False
    recall_count: int = 0


class DeltaContext(BaseModel):
    """Incremental context for subsequent turns (reduces network)."""

    base_version: int = Field(default=1, ge=1)
    append_messages: list[dict[str, str]] = Field(default_factory=list)
    context_version: int = Field(default=1, ge=1)
    """New version after this turn. CLI sends this back as context_version on next turn."""


# In-memory version tracker (per session)
_session_versions: dict[str, int] = {}


def get_context_version(session_id: str | None) -> int:
    """Get current context version for a session."""
    if not session_id:
        return 0
    return _session_versions.get(session_id, 0)


def bump_context_version(session_id: str | None) -> int:
    """Increment and return the context version."""
    if not session_id:
        return 1
    v = _session_versions.get(session_id, 0) + 1
    _session_versions[session_id] = v
    return v


class InferencePlan(BaseModel):
    """Complete inference plan sent from VPS to CLI.

    Schema version: inference_plan/v1
    """

    plan_schema: Literal["inference_plan/v1"] = Field(
        default="inference_plan/v1",
        alias="schema",
        description="Schema version identifier"
    )
    request_id: str = Field(..., description="Unique request ID for audit")
    chat_session_id: str | None = None
    work_item_id: str | None = None
    model: ModelSpec
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_catalog: list[str] = Field(default_factory=list)
    policy_digest: PolicyDigest
    context_meta: ContextMeta = Field(default_factory=ContextMeta)
    delta: DeltaContext | None = None


class PlanRequest(BaseModel):
    """Request to generate an InferencePlan (without LLM call)."""

    text: str = Field(..., min_length=1, description="User message")
    chat_session_id: str | None = None
    work_item_id: str | None = None
    agent_name: str | None = None
    model_override: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    tenant_id: str = Field(default="default")
    role: str = Field(default="developer")
    mode: str = Field(default="web")
    connector_alive: bool = False
    connector_id: str | None = None
    workspace_path: str | None = None
    focus_mode: bool = False
    # TEAM-specific
    session_mode: str = Field(default="continue", description="continue | fork | observe")
    handoff_from_session_id: str | None = None
    context_version: int | None = Field(default=None, description="For delta optimization")


class PlanResponse(BaseModel):
    """Response containing the InferencePlan."""

    plan: InferencePlan
    status: Literal["ok", "blocked", "error"] = "ok"
    block_reason: str | None = None


# ═══════════════════════════════════════════════════════════════
# Builder: ContextState → InferencePlan
# ═══════════════════════════════════════════════════════════════

def build_inference_plan(
    state,
    *,
    request_id: str,
    chat_session_id: str | None = None,
    work_item_id: str | None = None,
    model_id: str = "openai/gpt-4o-mini",
    profile: str = "balanced",
    max_tokens: int = 8192,
    temperature: float = 0.7,
    context_version: int | None = None,
) -> InferencePlan:
    """Build an InferencePlan from a ContextState (post-assembly).

    Called after assemble_context() to produce the plan the CLI
    will use for local inference.

    Args:
        state: Assembled ContextState from ContextEngine
        request_id: Unique request ID
        chat_session_id: Session ID
        work_item_id: Work item ID
        model_id: LLM model for the CLI to use
        profile: Inference profile
        max_tokens: Max tokens for this turn
        temperature: Model temperature
        context_version: Version for delta optimization

    Returns:
        InferencePlan ready for JSON serialization
    """
    # Build policy digest
    policy_json = json.dumps({
        "role": state.role,
        "dlp_enabled": state.dlp_enabled,
        "focus_mode": state.focus_mode,
        "role_tool_allowlist": sorted(state.role_tool_allowlist) if state.role_tool_allowlist else [],
        "session_rag_gate": state.session_rag_gate,
        "product_rag_gate": state.product_rag_gate,
    }, sort_keys=True)
    policy_sha = hashlib.sha256(policy_json.encode()).hexdigest()[:16]

    # Determine requires_approval_for based on role and mode
    requires_approval = _derive_approval_requirements(state)

    policy_digest = PolicyDigest(
        sha256=policy_sha,
        allowed_write_paths=_derive_allowed_paths(state),
        denied_tools=sorted(state.role_tool_allowlist) if state.role_tool_allowlist else [],
        requires_approval_for=requires_approval,
        dlp_enabled=state.dlp_enabled,
        focus_mode=state.focus_mode,
        role=state.role,
    )

    # Build model spec
    model = ModelSpec(
        model_id=model_id,
        profile=profile,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    # Build context meta
    context_meta = ContextMeta(
        layers=state.layers_applied,
        ui_trace_summary_pt=state.meta.get("context_policy_summary_pt", ""),
        build_ms=state.build_ms,
        session_truncated=state.session_truncated,
        recall_count=state.recall_count,
    )

    # Build delta if version provided
    delta = None
    if context_version and context_version > 0:
        delta = DeltaContext(
            base_version=context_version,
            append_messages=[],  # CLI handles caching
        )

    return InferencePlan(
        request_id=request_id,
        chat_session_id=chat_session_id,
        work_item_id=work_item_id,
        model=model,
        messages=state.messages,
        tools=state.tools,
        tool_catalog=state.tool_catalog,
        policy_digest=policy_digest,
        context_meta=context_meta,
        delta=delta,
    )


def _derive_allowed_paths(state) -> list[str]:
    """Derive allowed write paths from workspace and policy."""
    paths: list[str] = []
    if state.workspace_path:
        paths.append(state.workspace_path)
    if state.meta.get("work_item_workspace"):
        paths.append(state.meta["work_item_workspace"])
    return paths


def _derive_approval_requirements(state) -> list[str]:
    """Determine which tool actions require approval for this role."""
    if state.role in ("auditor", "reviewer"):
        # No write tools at all
        return ["file.write", "file.patch", "shell.exec", "file.delete"]

    if state.role == "observer":
        return ["file.write", "file.patch", "shell.exec", "file.delete"]

    # Developer/lead: approval for sensitive operations
    return ["shell.exec"]  # Shell always needs approval in TEAM
