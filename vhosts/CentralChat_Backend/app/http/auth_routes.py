"""Public auth routes (login, refresh rotation, logout)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import allow_login_attempt
from app.auth import auth_db_configured, validate_email, verify_credentials
from app.config import (
    AGENT_TOOLS_ENABLED,
    AUTH_LOGIN_ENABLED,
    CENTRAL_FOCUS_MODE,
    CENTRAL_JWT_ACCESS_TTL_SECONDS,
    CENTRAL_JWT_CLIENT_ID_CLAIM,
    CENTRAL_JWT_MODE,
    CENTRAL_JWT_SECRET,
    CENTRAL_OIDC_ENABLED,
    CHAT_SESSIONS_ENABLED,
    COMPOSER_SEGMENTS_IN_STREAM_ENABLED,
    MODEL_ROUTER_URL,
    OPENROUTER_API_KEY,
    WIDGET_MULTI_SLOT_ENABLED,
)
from app.shared.public_capabilities import build_widget_feature_flags
from app.http.problem_details import problem_json_response
from app.auth import decode_refresh_token, mint_token_pair
from app.auth import (
    exchange_authorization_code,
    is_allowed_redirect_uri,
    oidc_configured,
    oidc_public_config,
    resolve_identity_from_token_response,
    resolve_oidc_profile_from_token_response,
)
from app.auth import is_jti_revoked, is_refresh_subject_revoked, revoke_jti

router_auth = APIRouter(tags=["Auth"])


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class LoginBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=512)


class LogoutBody(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class OidcExchangeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=4096)
    code_verifier: str = Field(..., min_length=43, max_length=128)
    redirect_uri: str = Field(..., min_length=8, max_length=2048)


def auth_build_epoch() -> str:
    """Fingerprint for UI: muda quando CENTRAL_JWT_SECRET muda (reinício do orquestrador)."""
    raw = (CENTRAL_JWT_SECRET or "jwt-off").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def auth_public_snapshot() -> dict[str, Any]:
    jwt_on = CENTRAL_JWT_MODE != "off"
    oidc_ready = CENTRAL_OIDC_ENABLED and oidc_configured()
    oidc_cfg = oidc_public_config() if oidc_ready else None
    model_router_configured = bool((MODEL_ROUTER_URL or "").strip()) or bool(OPENROUTER_API_KEY)
    widget_feature_flags = build_widget_feature_flags(
        model_router_configured=model_router_configured,
        widget_multi_slot_enabled=bool(WIDGET_MULTI_SLOT_ENABLED),
        composer_segments_in_stream=bool(COMPOSER_SEGMENTS_IN_STREAM_ENABLED),
    )
    out: dict[str, Any] = {
        "jwt_mode": CENTRAL_JWT_MODE,
        "auth_login_enabled": bool(jwt_on and AUTH_LOGIN_ENABLED and auth_db_configured()),
        "auth_refresh_enabled": jwt_on,
        "auth_oidc_configured": bool(jwt_on and oidc_ready),
        "auth_oidc_enabled": bool(jwt_on and oidc_cfg is not None),
        "model_router_configured": model_router_configured,
        "chat_sessions_enabled": bool(CHAT_SESSIONS_ENABLED),
        "agent_tools_enabled": bool(AGENT_TOOLS_ENABLED),
        "central_focus_mode": bool(CENTRAL_FOCUS_MODE),
        "widget_multi_slot_enabled": bool(WIDGET_MULTI_SLOT_ENABLED),
        "cloud_models_allowlist_edit_enabled": False,  # M4: replaced by per-user user_cloud_models
        "widget_feature_flags": dict(widget_feature_flags),
        "auth_build_epoch": auth_build_epoch(),
    }
    if oidc_cfg is not None:
        out["oidc"] = oidc_cfg
    return out


@router_auth.get("/auth/public-config")
def auth_public_config() -> dict[str, Any]:
    """Bootstrap da UI (sem Bearer) — flags mínimas de autenticação."""
    return auth_public_snapshot()


@router_auth.post("/auth/login")
def auth_login(body: LoginBody, request: Request) -> dict[str, Any]:
    path = request.url.path
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    if not AUTH_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="login_disabled")
    if not auth_db_configured():
        return problem_json_response(
            status=503,
            type_suffix="auth_store_unavailable",
            detail="Autenticação por credenciais indisponível (base de dados não configurada).",
            instance=path,
        )

    if not validate_email(body.email):
        return problem_json_response(
            status=422,
            type_suffix="validation-error",
            detail="Email inválido.",
            instance=path,
        )

    client_ip = request.client.host if request.client else ""
    email = str(body.email)
    ok_rl, retry_after = allow_login_attempt(client_ip=client_ip, email=email)
    if not ok_rl:
        resp = problem_json_response(
            status=429,
            type_suffix="login_rate_limited",
            detail="Demasiadas tentativas de login; tente mais tarde.",
            instance=path,
            extensions={"retry_after_seconds": retry_after},
        )
        if retry_after is not None:
            resp.headers["Retry-After"] = str(int(retry_after))
        return resp

    try:
        user, err = verify_credentials(email=email, password=body.password)
    except Exception:
        return problem_json_response(
            status=503,
            type_suffix="auth_store_unavailable",
            detail="Autenticação temporariamente indisponível.",
            instance=path,
        )

    if err == "account_disabled":
        return problem_json_response(
            status=403,
            type_suffix="account_disabled",
            detail="Conta desactivada.",
            instance=path,
        )
    if user is None:
        try:
            from app.audit_service import append_audit_event

            append_audit_event(
                action="auth.login_failed",
                resource=email[:320],
                client="web",
                ip=client_ip or None,
                metadata={"reason": "invalid_credentials"},
            )
        except Exception:
            pass
        return problem_json_response(
            status=401,
            type_suffix="invalid_credentials",
            detail="Email ou palavra-passe incorrectos.",
            instance=path,
        )

    try:
        from app.audit_service import append_audit_event

        append_audit_event(
            action="auth.login",
            tenant_id=user.client_id,
            user_id=user.id,
            client="web",
            ip=client_ip or None,
            metadata={"email": user.email},
        )
    except Exception:
        pass

    out = mint_token_pair(
        sub=user.id,
        client_id=user.client_id,
        email=user.email or "",
        display_name=user.display_name or "",
        role=user.role,
        must_change_password=user.must_change_password,
    )
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    return out


class ChangePasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=512)


@router_auth.post("/auth/change-password")
def auth_change_password(body: ChangePasswordBody, request: Request) -> dict[str, Any]:
    """Change own password (required when must_change_password is set)."""
    path = request.url.path
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")

    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return problem_json_response(
            status=401,
            type_suffix="missing_bearer_token",
            detail="Authorization Bearer em falta.",
            instance=path,
        )
    token = auth[7:].strip()
    try:
        from app.auth import change_user_password, decode_access_token, mint_token_pair

        payload = decode_access_token(token)
    except Exception:
        return problem_json_response(
            status=401,
            type_suffix="invalid_access_token",
            detail="Token de acesso inválido ou expirado.",
            instance=path,
        )

    sub = str(payload.get("sub") or "").strip()
    if not sub:
        return problem_json_response(
            status=401,
            type_suffix="invalid_access_token",
            detail="Token de acesso inválido.",
            instance=path,
        )

    try:
        user = change_user_password(
            user_id=sub,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except ValueError as exc:
        err = str(exc)
        if err == "invalid_current_password":
            return problem_json_response(
                status=401,
                type_suffix="invalid_current_password",
                detail="Palavra-passe actual incorrecta.",
                instance=path,
            )
        if err in ("password_too_short", "password_too_long", "password_unchanged"):
            detail = (
                "A nova palavra-passe deve ter pelo menos 8 caracteres e ser diferente da actual."
                if err != "password_unchanged"
                else "A nova palavra-passe deve ser diferente da actual."
            )
            return problem_json_response(
                status=422,
                type_suffix="validation-error",
                detail=detail,
                instance=path,
            )
        if err == "account_disabled":
            return problem_json_response(
                status=403,
                type_suffix="account_disabled",
                detail="Conta desactivada.",
                instance=path,
            )
        return problem_json_response(
            status=422,
            type_suffix="validation-error",
            detail="Pedido inválido.",
            instance=path,
        )

    try:
        from app.audit_service import append_audit_event

        client_ip = request.client.host if request.client else ""
        append_audit_event(
            action="auth.password_changed",
            tenant_id=user.client_id,
            user_id=user.id,
            client="web",
            ip=client_ip or None,
            metadata={"email": user.email, "forced": False},
        )
    except Exception:
        pass

    out = mint_token_pair(
        sub=user.id,
        client_id=user.client_id,
        email=user.email or "",
        display_name=user.display_name or "",
        role=user.role,
        must_change_password=False,
    )
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    return out


@router_auth.post("/auth/refresh")
def auth_refresh(body: RefreshBody) -> dict[str, Any]:
    """
    Rotate refresh token: invalidates presented `jti`, returns new access + refresh pair.
    Disabled when CENTRAL_JWT_MODE=off.
    """
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")

    try:
        payload = decode_refresh_token(body.refresh_token.strip())
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid_refresh_token: {exc}") from exc

    jti = str(payload.get("jti") or "")
    if not jti:
        raise HTTPException(status_code=401, detail="missing_jti")

    if is_jti_revoked(jti):
        raise HTTPException(status_code=401, detail="refresh_token_revoked")

    sub = str(payload.get("sub") or "").strip()
    cid = str(payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM) or "").strip()
    if not sub or not cid:
        raise HTTPException(status_code=401, detail="invalid_refresh_claims")

    try:
        iat = int(payload.get("iat"))
    except (TypeError, ValueError):
        iat = None
    if is_refresh_subject_revoked(sub=sub, iat_unix=iat):
        raise HTTPException(status_code=401, detail="refresh_token_revoked")

    try:
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid_refresh_exp") from exc

    revoke_jti(jti, exp)
    old_email = str(payload.get("email") or "")
    old_display_name = str(payload.get("display_name") or "")
    out = mint_token_pair(sub=sub, client_id=cid, email=old_email, display_name=old_display_name)
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    return out


@router_auth.post("/auth/oidc/exchange")
def auth_oidc_exchange(body: OidcExchangeBody, request: Request) -> dict[str, Any]:
    """Troca authorization code (PKCE) por par JWT interno (BFF)."""
    path = request.url.path
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    if not CENTRAL_OIDC_ENABLED or not oidc_configured():
        raise HTTPException(status_code=404, detail="oidc_disabled")
    if not is_allowed_redirect_uri(body.redirect_uri):
        return problem_json_response(
            status=422,
            type_suffix="validation-error",
            detail="redirect_uri não permitido.",
            instance=path,
        )
    try:
        token_response = exchange_authorization_code(
            code=body.code.strip(),
            code_verifier=body.code_verifier.strip(),
            redirect_uri=body.redirect_uri.strip(),
        )
        sub, client_id = resolve_identity_from_token_response(token_response)
        profile = resolve_oidc_profile_from_token_response(token_response)
    except ValueError as exc:
        err = str(exc)
        try:
            from app.audit_service import append_audit_event

            append_audit_event(
                action="auth.oidc_login_failed",
                resource=body.redirect_uri[:320] if body else None,
                metadata={"error": err, "reason": "validation"},
            )
        except Exception:
            pass
        if err == "tenant_not_provisioned":
            return problem_json_response(
                status=403,
                type_suffix="tenant_not_provisioned",
                detail="Utilizador sem tenant provisionado no IdP.",
                instance=path,
            )
        if err in (
            "redirect_uri_not_allowed",
            "missing_id_token",
            "missing_sub",
            "oidc_scopes_must_include_openid",
        ):
            return problem_json_response(
                status=422,
                type_suffix="validation-error",
                detail="Pedido OIDC inválido.",
                instance=path,
            )
        return problem_json_response(
            status=401,
            type_suffix="oidc_exchange_failed",
            detail="Falha na troca do código OIDC.",
            instance=path,
        )
    except jwt.PyJWTError as exc:
        logger.warning("OIDC id_token validation failed path=%s err=%s", path, exc)
        try:
            from app.audit_service import append_audit_event

            append_audit_event(
                action="auth.oidc_login_failed",
                resource=path,
                metadata={"error": "invalid_id_token"},
            )
        except Exception:
            pass
        return problem_json_response(
            status=401,
            type_suffix="invalid_id_token",
            detail="Token do IdP inválido.",
            instance=path,
        )
    except Exception as exc:
        logger.warning("OIDC exchange failed path=%s err=%s", path, exc, exc_info=True)
        try:
            from app.audit_service import append_audit_event

            append_audit_event(
                action="auth.oidc_login_failed",
                resource=path,
                metadata={"error": str(exc)[:500]},
            )
        except Exception:
            pass
        return problem_json_response(
            status=503,
            type_suffix="oidc_unavailable",
            detail="IdP temporariamente indisponível.",
            instance=path,
        )

    out = mint_token_pair(
        sub=sub,
        client_id=client_id,
        email=profile.get("email") or "",
        display_name=profile.get("display_name") or "",
        role=profile.get("role"),
    )
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    role = profile.get("role") or "developer"
    out["role"] = role
    try:
        from app.audit_service import append_audit_event

        client_ip = request.client.host if request.client else ""
        append_audit_event(
            action="auth.oidc_login",
            tenant_id=client_id,
            user_id=sub,
            client="web",
            ip=client_ip or None,
            metadata={
                "email": profile.get("email") or "",
                "role": role,
                "method": "oidc",
            },
        )
    except Exception:
        pass
    return out


@router_auth.post("/auth/logout")
def auth_logout(body: LogoutBody, request: Request) -> dict[str, Any]:
    """Revoga o refresh token apresentado (best-effort)."""
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    sub: str | None = None
    tenant: str | None = None
    try:
        payload = decode_refresh_token(body.refresh_token.strip())
        jti = str(payload.get("jti") or "")
        sub = str(payload.get("sub") or "") or None
        tenant = str(payload.get("client_id") or payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM) or "") or None
        exp = int(payload["exp"])
        if jti:
            revoke_jti(jti, exp)
    except Exception:
        pass
    try:
        from app.audit_service import append_audit_event

        client_ip = request.client.host if request.client else ""
        append_audit_event(
            action="auth.logout",
            tenant_id=tenant,
            user_id=sub,
            client="web",
            ip=client_ip or None,
        )
    except Exception:
        pass
    return {"ok": True}


class DeviceStartBody(BaseModel):
    client_label: str = Field(default="cli", max_length=64)


class DeviceTokenBody(BaseModel):
    device_code: str = Field(..., min_length=10, max_length=128)


class DeviceApproveBody(BaseModel):
    user_code: str = Field(..., min_length=6, max_length=16)
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)


class ApiKeyExchangeBody(BaseModel):
    api_key: str = Field(..., min_length=20, max_length=256)


@router_auth.post("/auth/device/start")
def auth_device_start(body: DeviceStartBody) -> dict[str, Any]:
    """C1.5 — inicia fluxo device code para CLI."""
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    from app.shared.cli_auth import start_device_flow

    return start_device_flow(client_label=body.client_label)


@router_auth.post("/auth/device/token")
def auth_device_token(body: DeviceTokenBody, request: Request) -> dict[str, Any]:
    """C1.5 — poll device code até aprovação."""
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    from app.shared.cli_auth import poll_device_token

    result = poll_device_token(body.device_code.strip())
    if result.get("error"):
        err = str(result["error"])
        if err == "authorization_pending":
            return problem_json_response(
                status=428,
                type_suffix="authorization_pending",
                detail="Aguardando aprovação do utilizador.",
                instance=request.url.path,
            )
        if err == "expired_token":
            return problem_json_response(
                status=400,
                type_suffix="expired_device_code",
                detail="Device code expirado.",
                instance=request.url.path,
            )
        return problem_json_response(
            status=401,
            type_suffix="device_auth_failed",
            detail="Device code inválido ou negado.",
            instance=request.url.path,
        )
    out = mint_token_pair(
        sub=str(result["sub"]),
        client_id=str(result["client_id"]),
        email=str(result.get("email") or ""),
        role=str(result.get("role") or "developer"),
    )
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    out["role"] = result.get("role") or "developer"
    try:
        from app.audit_service import append_audit_event

        append_audit_event(
            action="auth.device_login",
            tenant_id=str(result["client_id"]),
            user_id=str(result["sub"]),
            client="cli",
            metadata={"method": "device_code"},
        )
    except Exception:
        pass
    return out


@router_auth.post("/auth/device/approve")
def auth_device_approve(body: DeviceApproveBody, request: Request) -> dict[str, Any]:
    """Aprova device code com credenciais locais (web ou manual)."""
    if CENTRAL_JWT_MODE == "off" or not AUTH_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    if not auth_db_configured():
        raise HTTPException(status_code=503, detail="auth_db_not_configured")
    if not allow_login_attempt(body.email):
        raise HTTPException(status_code=429, detail="rate_limited")
    user, err = verify_credentials(email=body.email.strip(), password=body.password)
    if err == "account_disabled":
        raise HTTPException(status_code=403, detail="account_disabled")
    if not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    from app.shared.cli_auth import approve_device_code

    ok = approve_device_code(
        body.user_code.strip(),
        sub=str(user.id),
        tenant_id=str(user.client_id),
        email=str(user.email or ""),
        role=str(user.role or "developer"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="device_code_not_found_or_expired")
    return {"ok": True, "user_code": body.user_code.strip().upper()}


@router_auth.post("/auth/api-key/exchange")
def auth_api_key_exchange(body: ApiKeyExchangeBody, request: Request) -> dict[str, Any]:
    """C1.5 — troca API key por par JWT (CLI)."""
    if CENTRAL_JWT_MODE == "off":
        raise HTTPException(status_code=404, detail="endpoint_disabled")
    from app.shared.cli_auth import validate_api_key

    ctx = validate_api_key(body.api_key.strip())
    if not ctx:
        return problem_json_response(
            status=401,
            type_suffix="invalid_api_key",
            detail="API key inválida ou revogada.",
            instance=request.url.path,
        )
    out = mint_token_pair(
        sub=str(ctx["sub"]),
        client_id=str(ctx["client_id"]),
        role=str(ctx.get("role") or "developer"),
    )
    out["expires_in"] = CENTRAL_JWT_ACCESS_TTL_SECONDS
    out["role"] = ctx.get("role") or "developer"
    try:
        from app.audit_service import append_audit_event

        append_audit_event(
            action="auth.api_key_login",
            tenant_id=str(ctx["client_id"]),
            user_id=str(ctx["sub"]),
            client="cli",
            metadata={"key_id": ctx.get("key_id"), "label": ctx.get("label")},
        )
    except Exception:
        pass
    return out
