"""
T19.4 — Atena suggestions endpoint (stub).

Endpoint reservado para o meta-agente Atena. Actualmente retorna
uma lista vazia. A lógica real será implementada quando o Atena
estiver activo (CENTRAL_ATENA_ENABLED=1).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

router_atena = APIRouter(prefix="/atena", tags=["Atena"])


@router_atena.get("/suggestions")
async def get_suggestions(
    tenant_id: str = Query("default", description="Tenant ID"),
    user_id: str | None = Query(None, description="User ID (opcional)"),
    kind: str | None = Query(None, description="Filtrar por kind"),
    limit: int = Query(10, ge=1, le=100, description="Máx. sugestões"),
):
    """
    Retorna sugestões do Atena para o tenant/user.

    ESTADO ACTUAL: Stub — retorna lista vazia.
    Futuro: query à tabela atena_observations com filtros.
    """
    return {
        "suggestions": [],
        "meta": {
            "atena_enabled": False,
            "observation_count": 0,
            "note": "Atena está em modo stub (CENTRAL_ATENA_ENABLED=0)."
        }
    }


@router_atena.get("/status")
async def get_atena_status():
    """
    Estado actual do subsistema Atena.
    """
    return {
        "enabled": False,
        "phase": "T19",
        "status": "stub",
        "description": "Infra-estrutura preparada. Lógica pendente de implementação."
    }
