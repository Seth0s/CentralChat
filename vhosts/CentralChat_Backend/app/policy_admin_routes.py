"""ContextPolicy Admin — CRUD endpoints for tenant policy configuration.

GET  /admin/policy          — read current policy
PUT  /admin/policy          — update policy settings
POST /admin/policy/reset    — reset to defaults

Policy is stored in PG tenant_policies and applied via resolve_policy().
Admin-only: requires 'admin' or 'lead' role.

Design: docs discussion — policy configured via UI Admin, not env vars.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.context_policy import AutoGate

logger = logging.getLogger(__name__)

router_policy_admin = APIRouter(prefix="/admin", tags=["Admin"])


# ═══════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════

class PolicyUpdateBody(BaseModel):
    """Fields that can be updated via admin UI."""
    max_context_tokens: int | None = Field(default=None, ge=8000, le=2_000_000)
    rag_char_budget: int | None = Field(default=None, ge=1000, le=100_000)
    verbatim_tail_messages: int | None = Field(default=None, ge=5, le=100)
    max_tool_schemas: int | None = Field(default=None, ge=1, le=50)
    dlp_enabled: bool | None = None
    focus_mode: bool | None = None
    tool_selection: str | None = Field(default=None, pattern="^(rag|keyword|full)$")
    session_rag: str | None = Field(default=None, pattern="^(always_if_session|semantic_gate|never)$")
    document_rag: str | None = Field(default=None, pattern="^(if_active_doc|never)$")
    memory_recall: str | None = Field(default=None, pattern="^(semantic_gate|never)$")
    product_rag: str | None = Field(default=None, pattern="^(intent_gate|never)$")
    playbook: str | None = Field(default=None, pattern="^(keyword_gate|never)$")
    role_tool_allowlist: list[str] | None = None


class PolicyResponse(BaseModel):
    """Current policy state."""
    tenant_id: str
    policy: dict[str, Any]
    source: str  # "defaults" | "pg" | "env"


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@router_policy_admin.get("/policy", response_model=PolicyResponse)
def admin_get_policy(tenant_id: str = "default") -> PolicyResponse:
    """Read current context policy for a tenant."""
    from app.context_policy import resolve_policy

    policy = resolve_policy(tenant_id=tenant_id)
    source = "pg" if _has_tenant_override(tenant_id) else "defaults"

    return PolicyResponse(
        tenant_id=tenant_id,
        policy={
            "max_context_tokens": policy.max_context_tokens,
            "rag_char_budget": policy.rag_char_budget,
            "verbatim_tail_messages": policy.verbatim_tail_messages,
            "max_tool_schemas": policy.max_tool_schemas,
            "dlp_enabled": policy.dlp_enabled,
            "focus_mode": policy.focus_mode,
            "tool_selection": policy.tool_selection,
            "gates": {
                "session_rag": policy.session_rag.value,
                "document_rag": policy.document_rag.value,
                "memory_recall": policy.memory_recall.value,
                "product_rag": policy.product_rag.value,
                "playbook": policy.playbook.value,
            },
            "role_tool_allowlist": sorted(policy.role_tool_allowlist) if policy.role_tool_allowlist else [],
        },
        source=source,
    )


@router_policy_admin.put("/policy")
def admin_update_policy(body: PolicyUpdateBody, tenant_id: str = "default") -> dict[str, Any]:
    """Update context policy for a tenant."""
    from app.shared.rbac import require_any_role
    require_any_role("admin", "lead")

    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if not memory_db_enabled():
            raise HTTPException(status_code=503, detail="memory_db_disabled")

        updates = body.model_dump(exclude_none=True)
        # Flatten gate fields
        gates = {}
        for gate_field in ("session_rag", "document_rag", "memory_recall", "product_rag", "playbook"):
            if gate_field in updates:
                gates[gate_field] = updates.pop(gate_field)
        if "role_tool_allowlist" in updates:
            updates["role_tool_allowlist"] = ",".join(updates["role_tool_allowlist"])
        if gates:
            updates["gates"] = ",".join(f"{k}={v}" for k, v in gates.items())

        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            _ensure_policy_table(cur)
            set_clauses = ", ".join(f"{k}=%s" for k in updates)
            values = list(updates.values()) + [tenant_id]
            cur.execute(
                f"""INSERT INTO tenant_policies (tenant_id, {', '.join(updates.keys())}, updated_at)
                    VALUES (%s, {', '.join(['%s'] * len(updates))}, now())
                    ON CONFLICT (tenant_id) DO UPDATE
                    SET {set_clauses}, updated_at = now()""",
                [tenant_id] + values,
            )

        return {"ok": True, "tenant_id": tenant_id, "updated": list(updates.keys())}
    except Exception as e:
        logger.exception("Policy update failed")
        raise HTTPException(status_code=500, detail=str(e))


@router_policy_admin.post("/policy/reset")
def admin_reset_policy(tenant_id: str = "default") -> dict[str, Any]:
    """Reset policy to defaults."""
    from app.shared.rbac import require_any_role
    require_any_role("admin", "lead")

    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if memory_db_enabled():
            with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM tenant_policies WHERE tenant_id=%s", (tenant_id,))
    except Exception:
        pass

    return {"ok": True, "tenant_id": tenant_id, "message": "Policy reset to defaults"}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _ensure_policy_table(cur) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS tenant_policies (
            tenant_id TEXT PRIMARY KEY,
            max_context_tokens INT,
            rag_char_budget INT,
            verbatim_tail_messages INT,
            max_tool_schemas INT,
            dlp_enabled BOOLEAN,
            focus_mode BOOLEAN,
            tool_selection TEXT,
            gates TEXT,
            role_tool_allowlist TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );"""
    )


def _has_tenant_override(tenant_id: str) -> bool:
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled
        if not memory_db_enabled():
            return False
        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tenant_policies WHERE tenant_id=%s", (tenant_id,))
            return cur.fetchone() is not None
    except Exception:
        return False
