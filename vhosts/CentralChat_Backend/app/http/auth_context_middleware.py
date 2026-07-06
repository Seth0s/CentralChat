"""JWT Bearer → tenant context (`client_id`) for multi-tenant L4 (Fase 4)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.config import CENTRAL_JWT_CLIENT_ID_CLAIM, CENTRAL_JWT_MODE
from app.http.problem_details import problem_json_response
from app.shared.tenant_rate_limit import maybe_rate_limit_response
from app.auth import decode_access_token
from app.shared.tenant_context import set_tenant_context
from app.shared.tenant_paths import sanitize_client_id

logger = logging.getLogger(__name__)

_PASSWORD_CHANGE_ALLOWED: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/auth/change-password"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/refresh"),
    ("GET", "/auth/public-config"),
})


def _is_public_route(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    if path in ("/health", "/health/ready", "/metrics", "/openapi.json"):
        return True
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    if method == "POST" and path in (
        "/auth/refresh",
        "/auth/login",
        "/auth/logout",
        "/auth/oidc/exchange",
        "/auth/device/start",
        "/auth/device/token",
        "/auth/device/approve",
        "/auth/api-key/exchange",
    ):
        return True
    if method == "GET" and path == "/auth/public-config":
        return True
    return False


def install_auth_context_middleware(app: FastAPI) -> None:
    """Inner middleware: validates access JWT when CENTRAL_JWT_MODE is optional/required."""

    @app.middleware("http")
    async def auth_context_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if CENTRAL_JWT_MODE == "off":
            set_tenant_context(client_id=None, sub=None)
            rl = maybe_rate_limit_response(request)
            if rl is not None:
                return rl
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path
        if _is_public_route(method, path):
            set_tenant_context(client_id=None, sub=None)
            return await call_next(request)

        auth = request.headers.get("Authorization") or ""
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

        api_key = (request.headers.get("X-Central-Api-Key") or "").strip()
        if not token and api_key:
            from app.shared.cli_auth import validate_api_key

            key_ctx = validate_api_key(api_key)
            if not key_ctx:
                return problem_json_response(
                    status=401,
                    type_suffix="invalid_api_key",
                    detail="API key inválida ou revogada.",
                    instance=path,
                )
            try:
                cid = sanitize_client_id(str(key_ctx.get("client_id") or ""))
            except ValueError:
                return problem_json_response(
                    status=403,
                    type_suffix="invalid_client_id",
                    detail="Tenant inválido na API key.",
                    instance=path,
                )
            sub = str(key_ctx.get("sub") or "").strip() or None
            set_tenant_context(client_id=cid, sub=sub)
            from app.shared.rbac import set_current_role

            set_current_role(str(key_ctx.get("role") or "developer").strip().lower())
            rl = maybe_rate_limit_response(request)
            if rl is not None:
                return rl
            return await call_next(request)

        if not token:
            if CENTRAL_JWT_MODE == "required":
                return problem_json_response(
                    status=401,
                    type_suffix="missing_bearer_token",
                    detail="Authorization Bearer em falta.",
                    instance=path,
                )
            set_tenant_context(client_id=None, sub=None)
            rl = maybe_rate_limit_response(request)
            if rl is not None:
                return rl
            return await call_next(request)

        try:
            payload = decode_access_token(token)
        except Exception as exc:  # noqa: BLE001 — PyJWT raises subclasses
            logger.info("JWT access reject path=%s err=%s", path, exc)
            return problem_json_response(
                status=401,
                type_suffix="invalid_access_token",
                detail="Token de acesso inválido ou expirado.",
                instance=path,
            )

        raw_cid = payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM)
        sub = str(payload.get("sub") or "").strip() or None
        try:
            cid = sanitize_client_id(str(raw_cid or ""))
        except ValueError:
            return problem_json_response(
                status=403,
                type_suffix="invalid_client_id",
                detail="Claim de cliente inválida no token.",
                instance=path,
            )

        set_tenant_context(client_id=cid, sub=sub)
        role = str(payload.get("role") or "developer").strip().lower()
        from app.shared.rbac import set_current_role

        set_current_role(role)
        if payload.get("must_change_password"):
            if (method, path) not in _PASSWORD_CHANGE_ALLOWED:
                return problem_json_response(
                    status=403,
                    type_suffix="password_change_required",
                    detail="Deve alterar a palavra-passe antes de continuar.",
                    instance=path,
                )
        rl = maybe_rate_limit_response(request)
        if rl is not None:
            return rl
        return await call_next(request)
