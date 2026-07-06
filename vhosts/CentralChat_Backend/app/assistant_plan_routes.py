"""Assistant plan routes — TEAM mode InferencePlan endpoint.

POST /assistant/plan — Assembles context via ContextEngine, returns
InferencePlan WITHOUT calling the LLM. The CLI uses the plan to call
the LLM locally.

Design doc: docs/CLI_RUNTIME_MODES.md §4.2, TEAM-0
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.inference_plan import (
    InferencePlan,
    ModelSpec,
    PolicyDigest,
    ContextMeta,
    PlanRequest,
    PlanResponse,
    build_inference_plan,
)

logger = logging.getLogger(__name__)

router_plan = APIRouter(tags=["TEAM"])


@router_plan.post("/assistant/plan", response_model=PlanResponse)
async def generate_plan(req: PlanRequest) -> PlanResponse:
    """Generate an InferencePlan for TEAM hybrid inference.

    This endpoint replaces /assistant/text/stream for TEAM mode.
    It assembles context using ContextEngine but does NOT call the LLM.
    The CLI receives the plan and calls the LLM locally.

    Flow:
    1. Validate request (DLP, policy)
    2. Call ContextEngine.assemble_context()
    3. Build InferencePlan from assembled state
    4. Return plan to CLI
    """
    import uuid

    request_id = str(uuid.uuid4())

    # ── DLP pre-check ──────────────────────────────────────────
    if req.tenant_id != "default":  # DLP is per-tenant in TEAM
        try:
            from app.shared.dlp_scanner import scan_prompt_text

            result = scan_prompt_text(req.text, tenant_id=req.tenant_id)
            if not result.allowed:
                return PlanResponse(
                    plan=InferencePlan(
                        request_id=request_id,
                        model=ModelSpec(model_id="blocked", profile="none", max_tokens=0, temperature=0),
                        messages=[],
                        tools=[],
                        tool_catalog=[],
                        policy_digest=PolicyDigest(
                            sha256="blocked", allowed_write_paths=[],
                            denied_tools=[], requires_approval_for=[],
                            dlp_enabled=True, focus_mode=False, role=req.role,
                        ),
                        context_meta=ContextMeta(),
                    ),
                    status="blocked",
                    block_reason=result.message_pt or "DLP blocked",
                )
        except Exception:
            logger.debug("DLP pre-check failed", exc_info=True)

    # ── Assemble context ───────────────────────────────────────
    try:
        from app.context_engine import assemble_context_sync

        state = assemble_context_sync(
            request_id=request_id,
            user_text=req.text,
            history=req.history,
            tenant_id=req.tenant_id,
            user_id="",  # TEAM: user_id comes from JWT (not implemented yet)
            role=req.role,
            session_id=req.chat_session_id,
            work_item_id=req.work_item_id,
            agent_name=req.agent_name,
            mode=req.mode,
            connector_alive=req.connector_alive,
            connector_id=req.connector_id,
            workspace_path=req.workspace_path,
            focus_mode=req.focus_mode,
            handoff_from_session_id=req.handoff_from_session_id,
            session_mode=req.session_mode,
        )
    except Exception as e:
        logger.exception("Context assembly failed for plan")
        raise HTTPException(status_code=500, detail=f"Context assembly failed: {e}")

    # ── Build plan ─────────────────────────────────────────────
    model_id = req.model_override or "openai/gpt-4o-mini"

    plan = build_inference_plan(
        state,
        request_id=request_id,
        chat_session_id=req.chat_session_id,
        work_item_id=req.work_item_id,
        model_id=model_id,
        context_version=req.context_version,
    )

    return PlanResponse(
        plan=plan,
        status="ok",
    )
