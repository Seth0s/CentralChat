"""Tenant domain — per-tenant configuration CRUD, middleware, defaults fallback.

T1: Tenant Config Table + CRUD + Middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import (
    CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT,
    CENTRAL_DEFAULT_CLIENT_ID,
    CENTRAL_QUOTA_PER_TENANT_PER_HOUR,
    CENTRAL_RATE_LIMIT_PER_WINDOW,
    CENTRAL_RATE_LIMIT_WINDOW_SECONDS,
)
from app.shared.inference_governance import validate_tenant_models_allowlist
from app.shared.rbac import require_any_role
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# MODEL
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TenantConfig:
    tenant_id: str
    display_name: str = ""
    max_concurrent_streams: int = 3
    rate_limit_per_window: int = 60
    rate_limit_window_seconds: int = 60
    features_json: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def defaults(cls, tenant_id: str) -> TenantConfig:
        """Fallback from env vars when no DB row exists."""
        return cls(
            tenant_id=tenant_id,
            max_concurrent_streams=int(CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT),
            rate_limit_per_window=int(CENTRAL_RATE_LIMIT_PER_WINDOW),
            rate_limit_window_seconds=int(CENTRAL_RATE_LIMIT_WINDOW_SECONDS),
            features_json={
                "quota_per_hour": int(CENTRAL_QUOTA_PER_TENANT_PER_HOUR),
            },
        )


# ═══════════════════════════════════════════════════════════════════
# STORE
# ═══════════════════════════════════════════════════════════════════


def _ensure_tenant_config_table() -> None:
    if not memory_db_enabled():
        return
    with connect_pg(tenant_id=CENTRAL_DEFAULT_CLIENT_ID) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_config (
                tenant_id               TEXT PRIMARY KEY,
                display_name            TEXT NOT NULL DEFAULT '',
                max_concurrent_streams  INT DEFAULT 3,
                rate_limit_per_window   INT DEFAULT 60,
                rate_limit_window_seconds INT DEFAULT 60,
                features_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


def get_tenant_config(tenant_id: str) -> TenantConfig | None:
    if not memory_db_enabled() or not tenant_id.strip():
        return None
    _ensure_tenant_config_table()
    tid = tenant_id.strip()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tenant_id, display_name, max_concurrent_streams,
                      rate_limit_per_window, rate_limit_window_seconds, features_json
               FROM tenant_config WHERE tenant_id = %s;""",
            (tid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        features = row[5] if isinstance(row[5], dict) else {}
        return TenantConfig(
            tenant_id=str(row[0]),
            display_name=str(row[1] or ""),
            max_concurrent_streams=int(row[2] or 3),
            rate_limit_per_window=int(row[3] or 60),
            rate_limit_window_seconds=int(row[4] or 60),
            features_json=features,
        )


def upsert_tenant_config(
    tenant_id: str,
    *,
    display_name: str | None = None,
    max_concurrent_streams: int | None = None,
    rate_limit_per_window: int | None = None,
    rate_limit_window_seconds: int | None = None,
    features_json: dict[str, Any] | None = None,
) -> TenantConfig:
    """Create or update a tenant config row. Returns the stored config."""
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    tid = tenant_id.strip()
    if not tid:
        raise ValueError("tenant_id_required")
    _ensure_tenant_config_table()

    existing = get_tenant_config(tid)
    if existing:
        name = display_name if display_name is not None else existing.display_name
        streams = max_concurrent_streams if max_concurrent_streams is not None else existing.max_concurrent_streams
        rlw = rate_limit_per_window if rate_limit_per_window is not None else existing.rate_limit_per_window
        rlws = rate_limit_window_seconds if rate_limit_window_seconds is not None else existing.rate_limit_window_seconds
        feat = features_json if features_json is not None else dict(existing.features_json)
    else:
        defaults = TenantConfig.defaults(tid)
        name = display_name or tid
        streams = max_concurrent_streams if max_concurrent_streams is not None else defaults.max_concurrent_streams
        rlw = rate_limit_per_window if rate_limit_per_window is not None else defaults.rate_limit_per_window
        rlws = rate_limit_window_seconds if rate_limit_window_seconds is not None else defaults.rate_limit_window_seconds
        feat = features_json if features_json is not None else defaults.features_json

    if isinstance(feat, dict) and isinstance(feat.get("models_allowlist"), list):
        validate_tenant_models_allowlist(feat["models_allowlist"])

    import json

    with connect_pg(tenant_id=CENTRAL_DEFAULT_CLIENT_ID) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tenant_config
                 (tenant_id, display_name, max_concurrent_streams,
                  rate_limit_per_window, rate_limit_window_seconds, features_json)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (tenant_id) DO UPDATE SET
                 display_name = EXCLUDED.display_name,
                 max_concurrent_streams = EXCLUDED.max_concurrent_streams,
                 rate_limit_per_window = EXCLUDED.rate_limit_per_window,
                 rate_limit_window_seconds = EXCLUDED.rate_limit_window_seconds,
                 features_json = EXCLUDED.features_json,
                 updated_at = now();""",
            (tid, name, streams, rlw, rlws, json.dumps(feat, ensure_ascii=False)),
        )

    return TenantConfig(
        tenant_id=tid,
        display_name=name,
        max_concurrent_streams=streams,
        rate_limit_per_window=rlw,
        rate_limit_window_seconds=rlws,
        features_json=feat,
    )


def list_all_tenant_configs() -> list[TenantConfig]:
    if not memory_db_enabled():
        return []
    _ensure_tenant_config_table()
    with connect_pg(tenant_id=CENTRAL_DEFAULT_CLIENT_ID) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tenant_id, display_name, max_concurrent_streams,
                      rate_limit_per_window, rate_limit_window_seconds, features_json
               FROM tenant_config ORDER BY tenant_id;"""
        )
        out: list[TenantConfig] = []
        for row in cur.fetchall() or []:
            features = row[5] if isinstance(row[5], dict) else {}
            out.append(
                TenantConfig(
                    tenant_id=str(row[0]),
                    display_name=str(row[1] or ""),
                    max_concurrent_streams=int(row[2] or 3),
                    rate_limit_per_window=int(row[3] or 60),
                    rate_limit_window_seconds=int(row[4] or 60),
                    features_json=features,
                )
            )
        return out


# ═══════════════════════════════════════════════════════════════════
# MIDDLEWARE — loads tenant config into request.state
# ═══════════════════════════════════════════════════════════════════

_TENANT_CONFIG_REQUEST_KEY = "tenant_config"


def get_tenant_config_from_request(request: Request) -> TenantConfig:
    """Retrieve tenant config set by middleware (or defaults fallback)."""
    cfg = getattr(request.state, _TENANT_CONFIG_REQUEST_KEY, None)
    if cfg is not None:
        return cfg
    tid = resolve_pg_tenant_id()
    return TenantConfig.defaults(tid)


def install_tenant_config_middleware(app: FastAPI) -> None:
    """Middleware: loads TenantConfig into request.state before each request."""

    async def _middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        tid = resolve_pg_tenant_id()
        cfg = None
        try:
            cfg = get_tenant_config(tid)
        except Exception:
            logger.debug("tenant_config_middleware: DB unavailable, using defaults for %s", tid, exc_info=True)

        if cfg is None:
            cfg = TenantConfig.defaults(tid)

        setattr(request.state, _TENANT_CONFIG_REQUEST_KEY, cfg)
        return await call_next(request)

    app.middleware("http")(_middleware)


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_tenant = APIRouter()


class TenantConfigPatchRequest(BaseModel):
    display_name: str | None = Field(None, max_length=256)
    max_concurrent_streams: int | None = Field(None, ge=1, le=100)
    rate_limit_per_window: int | None = Field(None, ge=1, le=100000)
    rate_limit_window_seconds: int | None = Field(None, ge=1, le=86400)
    features_json: dict[str, Any] | None = None


def _tenant_config_to_dict(cfg: TenantConfig) -> dict[str, Any]:
    return {
        "tenant_id": cfg.tenant_id,
        "display_name": cfg.display_name,
        "max_concurrent_streams": cfg.max_concurrent_streams,
        "rate_limit_per_window": cfg.rate_limit_per_window,
        "rate_limit_window_seconds": cfg.rate_limit_window_seconds,
        "features_json": cfg.features_json,
    }


@router_tenant.get("/admin/tenant-config", tags=["Admin"])
def admin_tenant_config_list() -> dict[str, Any]:
    """Lista todas as configurações de tenant (admin only)."""
    require_any_role("admin")
    try:
        configs = list_all_tenant_configs()
    except Exception:
        configs = []
    return {"items": [_tenant_config_to_dict(c) for c in configs]}


@router_tenant.get("/admin/tenant-config/{tenant_id}", tags=["Admin"])
def admin_tenant_config_get(tenant_id: str) -> dict[str, Any]:
    """Obtém config de um tenant específico (ou defaults se não existir)."""
    require_any_role("admin")
    cfg = get_tenant_config(tenant_id)
    if cfg is None:
        cfg = TenantConfig.defaults(tenant_id)
    return _tenant_config_to_dict(cfg)


@router_tenant.post("/admin/tenant-config/{tenant_id}", tags=["Admin"])
def admin_tenant_config_upsert(
    tenant_id: str,
    payload: TenantConfigPatchRequest,
) -> dict[str, Any]:
    """Cria ou actualiza a config de um tenant."""
    require_any_role("admin")
    patch = payload.model_dump(exclude_unset=True)
    try:
        cfg = upsert_tenant_config(tenant_id, **patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _tenant_config_to_dict(cfg)
