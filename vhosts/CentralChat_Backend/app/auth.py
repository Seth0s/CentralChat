"""Auth domain — users, OIDC, JWT, rate limiting, production policy, refresh revocation."""

from __future__ import annotations

from __future__ import annotations
from app import config as _cfg
from app.config import AUTH_LOGIN_ENABLED, CENTRAL_APP_ENV, CENTRAL_JWT_MODE, CENTRAL_OIDC_ENABLED
from app.config import AUTH_PASSWORD_PEPPER, AUTH_USERS_DB_URL, CENTRAL_BOOTSTRAP_ADMIN_DISPLAY_NAME
from app.config import CENTRAL_BOOTSTRAP_ADMIN_EMAIL, CENTRAL_BOOTSTRAP_ADMIN_ENABLED, CENTRAL_BOOTSTRAP_ADMIN_PASSWORD
from app.config import CENTRAL_DEFAULT_CLIENT_ID
from app.config import CENTRAL_DEFAULT_CLIENT_ID, CENTRAL_JWT_CLIENT_ID_CLAIM, CENTRAL_OIDC_STRICT_TENANT, CENTRAL_OIDC_TENANT_CLAIM
from app.config import CENTRAL_JWT_ACCESS_TTL_SECONDS, CENTRAL_JWT_ALGORITHM, CENTRAL_JWT_AUDIENCE, CENTRAL_JWT_CLIENT_ID_CLAIM, CENTRAL_JWT_ISSUER, CENTRAL_JWT_REFRESH_TTL_SECONDS, CENTRAL_JWT_SECRET
from app.config import CENTRAL_JWT_CLIENT_ID_CLAIM, CENTRAL_OIDC_ALLOWED_ALGORITHMS, CENTRAL_OIDC_CLIENT_ID, CENTRAL_OIDC_CLOCK_SKEW_SECONDS, CENTRAL_OIDC_JWKS_CACHE_SECONDS, CENTRAL_OIDC_RESOURCE_AUDIENCE
from app.config import CENTRAL_OIDC_CLIENT_ID, CENTRAL_OIDC_CLIENT_SECRET, CENTRAL_OIDC_REDIRECT_URIS, CENTRAL_OIDC_SCOPES
from app.config import CENTRAL_OIDC_DISCOVERY_BASE, CENTRAL_OIDC_DISCOVERY_CACHE_SECONDS, CENTRAL_OIDC_ISSUER_URL
from app.config import CENTRAL_OIDC_HTTP_BASE, CENTRAL_OIDC_ISSUER_URL
from collections import deque
from dataclasses import dataclass
from jwt import PyJWKClient
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
import httpx
import json
import jwt
import logging
import re
import threading
import time
import uuid


# ═══ OIDC_URLS ═══

"""Rewrite IdP URLs for server-side HTTP inside Compose/Podman (browser keeps localhost)."""

def idp_url_for_browser(url: str) -> str:
    """Discovery via rede interna pode trazer :8080; o browser usa CENTRAL_OIDC_ISSUER_URL (:8180 no host)."""
    if not CENTRAL_OIDC_ISSUER_URL or not url:
        return url
    marker = "/realms/"
    if marker not in url or marker not in CENTRAL_OIDC_ISSUER_URL:
        return url
    path = url[url.index(marker) :]
    pub_root = CENTRAL_OIDC_ISSUER_URL.split(marker, 1)[0].rstrip("/")
    return pub_root + path

def idp_url_for_server(url: str) -> str:
    """
    Discovery fetched on the internal network may advertise localhost:8080.
    Server-side HTTP must use CENTRAL_OIDC_HTTP_BASE (ex. central-keycloak-dev:8080).
    """
    if not CENTRAL_OIDC_HTTP_BASE or not url:
        return url
    parsed = urlparse(url)
    if "/realms/" not in parsed.path and "/realms/" not in url:
        return url
    internal = urlparse(CENTRAL_OIDC_HTTP_BASE)
    return urlunparse(
        (internal.scheme, internal.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


# ═══ OIDC_DISCOVERY ═══

"""OpenID Provider discovery document (cached)."""

logger = logging.getLogger(__name__)

_cache_doc: dict[str, Any] | None = None

_cache_expires_at: float = 0.0

def _discovery_url() -> str:
    base = (CENTRAL_OIDC_DISCOVERY_BASE or CENTRAL_OIDC_ISSUER_URL).rstrip("/")
    return f"{base}/.well-known/openid-configuration"

def reset_oidc_discovery_cache_for_tests() -> None:
    global _cache_doc, _cache_expires_at  # noqa: PLW0603
    _cache_doc = None
    _cache_expires_at = 0.0

def fetch_discovery_document(*, force_refresh: bool = False) -> dict[str, Any]:
    global _cache_doc, _cache_expires_at  # noqa: PLW0603
    now = time.time()
    if not force_refresh and _cache_doc is not None and now < _cache_expires_at:
        return _cache_doc

    url = _discovery_url()
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            doc = resp.json()
    except Exception as exc:
        logger.warning("OIDC discovery failed url=%s err=%s", url, exc)
        if _cache_doc is not None:
            return _cache_doc
        raise

    if not isinstance(doc, dict):
        raise ValueError("invalid_discovery_document")

    _cache_doc = doc
    _cache_expires_at = now + CENTRAL_OIDC_DISCOVERY_CACHE_SECONDS
    return doc

def get_discovery_endpoint(key: str) -> str:
    doc = fetch_discovery_document()
    val = doc.get(key)
    if not isinstance(val, str) or not val.strip():
        raise KeyError(key)
    return val.strip()

def get_oidc_issuer() -> str:
    """Canonical issuer (browser-facing). Prefer CENTRAL_OIDC_ISSUER_URL when set."""
    issuers = get_oidc_valid_issuers()
    if not issuers:
        raise ValueError("missing_issuer")
    return issuers[0]

def get_oidc_valid_issuers() -> tuple[str, ...]:
    """
    Issuers accepted when validating id_tokens.

    Keycloak dev often advertises :8080 on internal discovery while the browser uses
    :8180 (KC_HOSTNAME_PORT). Tokens from the BFF token call may carry either iss.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(raw: str) -> None:
        iss = raw.strip().rstrip("/")
        if iss and iss not in seen:
            seen.add(iss)
            ordered.append(iss)

    if CENTRAL_OIDC_ISSUER_URL:
        _add(CENTRAL_OIDC_ISSUER_URL)
    try:
        doc = fetch_discovery_document()
        raw = doc.get("issuer")
        if isinstance(raw, str):
            _add(raw)
    except Exception as exc:
        logger.debug("OIDC discovery issuer unavailable: %s", exc)

    return tuple(ordered)


# ═══ OIDC_TENANT ═══

"""Map IdP claims → tenant `client_id` (ADR-015)."""

def resolve_tenant_client_id(payload: dict[str, Any]) -> str:
    """
    Resolve effective tenant from id_token (or resource access token) claims.

    Raises ValueError("tenant_not_provisioned") when strict and no mapping exists.
    """
    claim_name = CENTRAL_OIDC_TENANT_CLAIM or CENTRAL_JWT_CLIENT_ID_CLAIM
    raw = payload.get(claim_name)
    if raw is None or str(raw).strip() == "":
        raw = payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM)
    if raw is not None and str(raw).strip():
        return str(raw).strip()

    if CENTRAL_OIDC_STRICT_TENANT:
        raise ValueError("tenant_not_provisioned")

    return CENTRAL_DEFAULT_CLIENT_ID


# ═══ OIDC_JWKS ═══

"""JWKS validation for IdP tokens (OIDC Core — ADR-015)."""

logger = logging.getLogger(__name__)

_jwk_client: PyJWKClient | None = None

def reset_oidc_jwks_client_for_tests() -> None:
    global _jwk_client  # noqa: PLW0603
    _jwk_client = None

def _jwks_client() -> PyJWKClient:
    global _jwk_client  # noqa: PLW0603
    if _jwk_client is None:
        jwks_uri = idp_url_for_server(get_discovery_endpoint("jwks_uri"))
        _jwk_client = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            lifespan=CENTRAL_OIDC_JWKS_CACHE_SECONDS,
        )
    return _jwk_client

def _audience_matches_client(payload: dict[str, Any], client_id: str) -> bool:
    """Keycloak often sets aud=account; azp holds the OAuth client_id (OIDC BFF)."""
    raw = payload.get("aud")
    if isinstance(raw, str):
        audiences = [raw]
    elif isinstance(raw, list):
        audiences = [str(x) for x in raw]
    else:
        audiences = []
    if client_id in audiences:
        return True
    return str(payload.get("azp") or "").strip() == client_id

def _decode_with_jwks(
    token: str,
    *,
    audience: str | None,
    require_sub: bool = True,
    verify_aud: bool = True,
) -> dict[str, Any]:
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
    except Exception as exc:
        logger.warning("OIDC JWKS key resolve failed: %s", exc, exc_info=True)
        raise jwt.InvalidTokenError("jwks_key_unavailable") from exc

    issuers = get_oidc_valid_issuers()
    if not issuers:
        raise jwt.InvalidTokenError("oidc_issuer_not_configured")
    leeway = CENTRAL_OIDC_CLOCK_SKEW_SECONDS
    require: list[str] = ["exp"]
    if require_sub:
        require.append("sub")

    decode_audience = audience if verify_aud else None
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=list(CENTRAL_OIDC_ALLOWED_ALGORITHMS),
        audience=decode_audience,
        issuer=issuers if len(issuers) > 1 else issuers[0],
        options={
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": verify_aud,
            "require": require,
        },
        leeway=leeway,
    )
    return payload

def decode_id_token(token: str) -> dict[str, Any]:
    """
    Validate OIDC id_token at BFF exchange.

    aud SHOULD be the OAuth client_id (RP). Keycloak may use aud=account with azp=client_id.
    Do not use CENTRAL_JWT_AUDIENCE (internal JWT).
    """
    if not CENTRAL_OIDC_CLIENT_ID:
        raise jwt.InvalidTokenError("oidc_client_id_not_configured")
    try:
        return _decode_with_jwks(
            token, audience=CENTRAL_OIDC_CLIENT_ID, require_sub=True, verify_aud=True
        )
    except jwt.InvalidAudienceError:
        payload = _decode_with_jwks(
            token, audience=None, require_sub=True, verify_aud=False
        )
        if not _audience_matches_client(payload, CENTRAL_OIDC_CLIENT_ID):
            raise jwt.InvalidAudienceError("id_token audience does not match OAuth client")
        return payload

def decode_oidc_resource_access_token(token: str) -> dict[str, Any]:
    """
    Optional: validate IdP access token on API (CENTRAL_JWT_MODE=hybrid only).

    Requires CENTRAL_OIDC_RESOURCE_AUDIENCE (resource/API identifier at the IdP).
    """
    aud = (CENTRAL_OIDC_RESOURCE_AUDIENCE or "").strip()
    if not aud:
        raise jwt.InvalidTokenError("oidc_resource_audience_not_configured")
    payload = _decode_with_jwks(token, audience=aud, require_sub=True)
    cid = resolve_tenant_client_id(payload)
    raw = payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM)
    if raw is None or str(raw).strip() == "":
        return {**payload, CENTRAL_JWT_CLIENT_ID_CLAIM: cid}
    return payload

def decode_oidc_jwt(token: str, *, expect_typ: str | None = "access") -> dict[str, Any]:
    """
    Back-compat wrapper: resource access validation for hybrid mode.

    Prefer decode_id_token at exchange and decode_oidc_resource_access_token for hybrid API.
    """
    payload = decode_oidc_resource_access_token(token)
    if expect_typ is not None:
        t = str(payload.get("typ") or "")
        if t and t != expect_typ:
            raise jwt.InvalidTokenError("unexpected_token_typ")
    return payload


# ═══ OIDC_CLIENT ═══

"""OIDC Authorization Code + PKCE (BFF token exchange — ADR-015)."""

logger = logging.getLogger(__name__)

def oidc_configured() -> bool:
    return bool(CENTRAL_OIDC_CLIENT_ID and CENTRAL_OIDC_CLIENT_SECRET and CENTRAL_OIDC_REDIRECT_URIS)

def default_redirect_uri() -> str:
    if not CENTRAL_OIDC_REDIRECT_URIS:
        return ""
    return CENTRAL_OIDC_REDIRECT_URIS[0]

def is_allowed_redirect_uri(uri: str) -> bool:
    u = (uri or "").strip()
    return bool(u) and u in CENTRAL_OIDC_REDIRECT_URIS

def _ensure_openid_scope() -> None:
    scopes = {s.strip() for s in CENTRAL_OIDC_SCOPES.split() if s.strip()}
    if "openid" not in scopes:
        raise ValueError("oidc_scopes_must_include_openid")

def oidc_public_config() -> dict[str, Any] | None:
    if not oidc_configured():
        return None
    try:
        end_session: str | None = None
        try:
            end_session = idp_url_for_browser(get_discovery_endpoint("end_session_endpoint"))
        except Exception:
            end_session = None
        authorization_endpoint = idp_url_for_browser(
            get_discovery_endpoint("authorization_endpoint")
        )
    except Exception as exc:
        logger.warning("OIDC public config unavailable: %s", exc)
        return None
    out: dict[str, Any] = {
        "authorization_endpoint": authorization_endpoint,
        "client_id": CENTRAL_OIDC_CLIENT_ID,
        "scopes": CENTRAL_OIDC_SCOPES,
        "redirect_uri": default_redirect_uri(),
    }
    if end_session:
        out["end_session_endpoint"] = end_session
    return out

def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    if not oidc_configured():
        raise RuntimeError("oidc_not_configured")
    if not is_allowed_redirect_uri(redirect_uri):
        raise ValueError("redirect_uri_not_allowed")
    _ensure_openid_scope()

    token_endpoint = idp_url_for_server(get_discovery_endpoint("token_endpoint"))
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            token_endpoint,
            data=data,
            auth=(CENTRAL_OIDC_CLIENT_ID, CENTRAL_OIDC_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            logger.info("OIDC token exchange failed status=%s", resp.status_code)
            raise ValueError("token_exchange_failed")
        body = resp.json()
    if not isinstance(body, dict):
        raise ValueError("invalid_token_response")
    return body

def resolve_identity_from_token_response(token_response: dict[str, Any]) -> tuple[str, str]:
    """Return (sub, client_id) from id_token only (OIDC Core)."""
    id_token = token_response.get("id_token")
    if not isinstance(id_token, str) or not id_token.strip():
        raise ValueError("missing_id_token")

    payload = decode_id_token(id_token.strip())
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        raise ValueError("missing_sub")
    cid = resolve_tenant_client_id(payload)
    return sub, cid


def map_role_from_oidc_payload(payload: dict[str, Any]) -> str:
    """H2 — map IdP groups claim to Central RBAC role."""
    from app.config import CENTRAL_OIDC_GROUP_ROLE_MAP, CENTRAL_OIDC_ROLE_CLAIM

    valid = frozenset({"viewer", "developer", "approver", "admin", "auditor"})
    direct = str(payload.get("role") or "").strip().lower()
    if direct in valid:
        return direct
    groups = payload.get(CENTRAL_OIDC_ROLE_CLAIM) or payload.get("groups") or []
    if isinstance(groups, str):
        groups = [groups]
    if isinstance(groups, list):
        for g in groups:
            mapped = CENTRAL_OIDC_GROUP_ROLE_MAP.get(str(g).strip())
            if mapped and mapped in valid:
                return mapped
    return "developer"


def resolve_oidc_profile_from_token_response(token_response: dict[str, Any]) -> dict[str, str]:
    """Email, display_name, role from id_token (H2 SSO production)."""
    id_token = token_response.get("id_token")
    if not isinstance(id_token, str) or not id_token.strip():
        raise ValueError("missing_id_token")
    payload = decode_id_token(id_token.strip())
    return {
        "email": str(payload.get("email") or ""),
        "display_name": str(payload.get("name") or payload.get("preferred_username") or ""),
        "role": map_role_from_oidc_payload(payload),
    }


# ═══ JWT_TOKENS ═══

"""HS256 access/refresh JWTs (Fase 4). Refresh rotation via `jti` revocation list."""

def _decode_options(*, verify_exp: bool) -> dict[str, Any]:
    return {"verify_signature": True, "verify_exp": verify_exp}

def mint_access_token(*, sub: str, client_id: str, email: str = "", display_name: str = "", extra_claims: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    body: dict[str, Any] = {
        "sub": sub,
        CENTRAL_JWT_CLIENT_ID_CLAIM: client_id,
        "iat": now,
        "exp": now + CENTRAL_JWT_ACCESS_TTL_SECONDS,
        "typ": "access",
    }
    if email:
        body["email"] = email
    if display_name:
        body["display_name"] = display_name
    if CENTRAL_JWT_AUDIENCE:
        body["aud"] = CENTRAL_JWT_AUDIENCE
    if CENTRAL_JWT_ISSUER:
        body["iss"] = CENTRAL_JWT_ISSUER
    if extra_claims:
        body.update(extra_claims)
    return jwt.encode(body, CENTRAL_JWT_SECRET, algorithm=CENTRAL_JWT_ALGORITHM)

def mint_refresh_token(*, sub: str, client_id: str, email: str = "", display_name: str = "", jti: str | None = None) -> tuple[str, str]:
    now = int(time.time())
    jti_out = jti or str(uuid.uuid4())
    body: dict[str, Any] = {
        "sub": sub,
        CENTRAL_JWT_CLIENT_ID_CLAIM: client_id,
        "iat": now,
        "exp": now + CENTRAL_JWT_REFRESH_TTL_SECONDS,
        "typ": "refresh",
        "jti": jti_out,
    }
    if email:
        body["email"] = email
    if display_name:
        body["display_name"] = display_name
    if CENTRAL_JWT_AUDIENCE:
        body["aud"] = CENTRAL_JWT_AUDIENCE
    if CENTRAL_JWT_ISSUER:
        body["iss"] = CENTRAL_JWT_ISSUER
    token = jwt.encode(body, CENTRAL_JWT_SECRET, algorithm=CENTRAL_JWT_ALGORITHM)
    return token, jti_out

def get_user_role(user_id: str) -> str:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT role FROM auth_users WHERE id=%s::uuid LIMIT 1", (user_id,))
                row = cur.fetchone()
                if row and row[0]:
                    role = str(row[0]).strip().lower()
                    if role in ("viewer", "developer", "approver", "admin", "auditor"):
                        return role
    except Exception:
        pass
    return "developer"


def mint_token_pair(
    *,
    sub: str,
    client_id: str,
    email: str = "",
    display_name: str = "",
    role: str | None = None,
    must_change_password: bool | None = None,
) -> dict[str, Any]:
    """Mint access + refresh (used by /auth/refresh rotation)."""
    r = (role or get_user_role(sub) or "developer").strip().lower()
    if r not in ("viewer", "developer", "approver", "admin", "auditor", "lead"):
        r = "developer"
    force_pwd_change = (
        user_must_change_password(sub) if must_change_password is None else bool(must_change_password)
    )
    extra_claims: dict[str, Any] = {"role": r}
    if force_pwd_change:
        extra_claims["must_change_password"] = True
    refresh, _jti = mint_refresh_token(sub=sub, client_id=client_id, email=email, display_name=display_name)
    access = mint_access_token(
        sub=sub,
        client_id=client_id,
        email=email,
        display_name=display_name,
        extra_claims=extra_claims,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "role": r,
        "must_change_password": force_pwd_change,
    }

def _decode_access_token_hs256(token: str) -> dict[str, Any]:
    aud = CENTRAL_JWT_AUDIENCE or None
    iss = CENTRAL_JWT_ISSUER or None
    payload = jwt.decode(
        token,
        CENTRAL_JWT_SECRET,
        algorithms=[CENTRAL_JWT_ALGORITHM],
        audience=aud,
        issuer=iss,
        options=_decode_options(verify_exp=True),
    )
    t = str(payload.get("typ") or "")
    if t not in ("", "access"):
        raise jwt.InvalidTokenError("not_an_access_token")
    cid = payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM)
    if cid is None or str(cid).strip() == "":
        raise jwt.InvalidTokenError("missing_client_id")
    return payload

def decode_access_token(token: str) -> dict[str, Any]:
    from app.config import CENTRAL_JWT_MODE

    if CENTRAL_JWT_MODE == "oidc":
        from app.oidc_jwks import decode_oidc_resource_access_token

        return decode_oidc_resource_access_token(token)

    if CENTRAL_JWT_MODE == "hybrid":
        try:
            return _decode_access_token_hs256(token)
        except jwt.PyJWTError:
            from app.oidc_jwks import decode_oidc_resource_access_token

            return decode_oidc_resource_access_token(token)

    return _decode_access_token_hs256(token)

def decode_refresh_token(token: str, *, verify_exp: bool = True) -> dict[str, Any]:
    aud = CENTRAL_JWT_AUDIENCE or None
    iss = CENTRAL_JWT_ISSUER or None
    payload = jwt.decode(
        token,
        CENTRAL_JWT_SECRET,
        algorithms=[CENTRAL_JWT_ALGORITHM],
        audience=aud,
        issuer=iss,
        options=_decode_options(verify_exp=verify_exp),
    )
    if str(payload.get("typ") or "") != "refresh":
        raise jwt.InvalidTokenError("not_a_refresh_token")
    if not payload.get("jti"):
        raise jwt.InvalidTokenError("missing_jti")
    cid = payload.get(CENTRAL_JWT_CLIENT_ID_CLAIM)
    if cid is None or str(cid).strip() == "":
        raise jwt.InvalidTokenError("missing_client_id")
    return payload


# ═══ AUTH_USERS_STORE ═══

"""Fase A — utilizadores para POST /auth/login (Postgres)."""

try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@dataclass
class AuthUserRow:
    id: str
    email: str
    client_id: str
    active: bool
    display_name: str = ""
    role: str = "developer"
    must_change_password: bool = False


_AUTH_USER_ROLES = frozenset({"admin", "lead", "developer", "auditor"})
_AUTH_LEGACY_ROLES = frozenset({"viewer", "reviewer", "approver"})


def _normalize_auth_role(role: str | None, *, allow_legacy: bool = True) -> str:
    r = (role or "").strip().lower() or "developer"
    allowed = _AUTH_USER_ROLES | (_AUTH_LEGACY_ROLES if allow_legacy else frozenset())
    if r not in allowed:
        raise ValueError("invalid_role")
    return r

def _connect():
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    url = (AUTH_USERS_DB_URL or "").strip()
    if not url:
        raise RuntimeError("auth_users_db_not_configured")
    return psycopg.connect(url, autocommit=True)

def ensure_auth_schema() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_clients (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  active BOOLEAN NOT NULL DEFAULT true,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                  id UUID PRIMARY KEY,
                  email TEXT NOT NULL UNIQUE,
                  password_hash TEXT NOT NULL,
                  client_id TEXT NOT NULL REFERENCES auth_clients(id),
                  display_name TEXT,
                  role TEXT NOT NULL DEFAULT 'developer',
                  active BOOLEAN NOT NULL DEFAULT true,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'developer';")
            cur.execute(
                """
                ALTER TABLE auth_users
                ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false;
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS auth_users_client_id_idx ON auth_users (client_id);
                """
            )
            cur.execute(
                """
                INSERT INTO auth_clients (id, name, active)
                VALUES (%s, %s, true)
                ON CONFLICT (id) DO NOTHING;
                """,
                (CENTRAL_DEFAULT_CLIENT_ID, CENTRAL_DEFAULT_CLIENT_ID),
            )

def count_auth_users() -> int:
    ensure_auth_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM auth_users;")
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def ensure_bootstrap_admin() -> AuthUserRow | None:
    """Create initial admin when auth DB is empty (GitLab-style root + changeme)."""
    if not CENTRAL_BOOTSTRAP_ADMIN_ENABLED:
        return None
    if not auth_db_configured():
        return None
    em = normalize_email(CENTRAL_BOOTSTRAP_ADMIN_EMAIL)
    if not validate_email(em):
        logger.warning("bootstrap admin skipped: invalid email %r", CENTRAL_BOOTSTRAP_ADMIN_EMAIL)
        return None
    pwd = (CENTRAL_BOOTSTRAP_ADMIN_PASSWORD or "").strip()
    if not pwd:
        logger.warning("bootstrap admin skipped: empty CENTRAL_BOOTSTRAP_ADMIN_PASSWORD")
        return None
    ensure_auth_schema()
    if count_auth_users() > 0:
        return None
    cid = CENTRAL_DEFAULT_CLIENT_ID
    pwd_hash = hash_password(pwd)
    uid = uuid.uuid4()
    display = (CENTRAL_BOOTSTRAP_ADMIN_DISPLAY_NAME or "root").strip() or "root"
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM auth_users;")
        if int((cur.fetchone() or [0])[0]) > 0:
            return None
        cur.execute(
            """
            INSERT INTO auth_users (
              id, email, password_hash, client_id, display_name, active, role, must_change_password
            )
            VALUES (%s, %s, %s, %s, %s, true, 'admin', true)
            RETURNING id, email, client_id, display_name, active, role, must_change_password;
            """,
            (uid, em, pwd_hash, cid, display),
        )
        row = cur.fetchone()
    if not row:
        return None
    logger.warning(
        "bootstrap admin created email=%s — change password on first login",
        em,
    )
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=str(row[5] or "admin"),
        must_change_password=bool(row[6]),
    )


def validate_new_password(password: str) -> None:
    plain = (password or "").strip()
    if len(plain) < 8:
        raise ValueError("password_too_short")
    if len(plain) > 512:
        raise ValueError("password_too_long")


def user_must_change_password(user_id: str) -> bool:
    uid = (user_id or "").strip()
    if not uid:
        return False
    ensure_auth_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT must_change_password FROM auth_users WHERE id = %s LIMIT 1;",
            (uid,),
        )
        row = cur.fetchone()
    return bool(row[0]) if row else False

def hash_password(plain: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt_not_installed")
    peppered = f"{plain}{AUTH_PASSWORD_PEPPER}".encode("utf-8")
    return bcrypt.hashpw(peppered, bcrypt.gensalt(rounds=12)).decode("ascii")

def verify_password(plain: str, password_hash: str) -> bool:
    if bcrypt is None:
        raise RuntimeError("bcrypt_not_installed")
    try:
        peppered = f"{plain}{AUTH_PASSWORD_PEPPER}".encode("utf-8")
        return bcrypt.checkpw(peppered, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()

def validate_email(email: str) -> bool:
    e = normalize_email(email)
    return bool(e) and len(e) <= 320 and bool(_EMAIL_RE.match(e))


def _would_remove_last_active_admin(*, user_id: str, client_id: str, role: str | None, active: bool | None) -> bool:
    if role == "admin" and active is not False:
        return False
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, active
            FROM auth_users
            WHERE id = %s AND client_id = %s
            LIMIT 1;
            """,
            (user_id, client_id),
        )
        target = cur.fetchone()
        if not target:
            return False
        current_role = str(target[0] or "").strip().lower()
        current_active = bool(target[1])
        if current_role != "admin" or not current_active:
            return False
        next_role = role if role is not None else current_role
        next_active = active if active is not None else current_active
        if next_role == "admin" and next_active:
            return False
        cur.execute(
            """
            SELECT COUNT(*)
            FROM auth_users
            WHERE client_id = %s AND role = 'admin' AND active = true;
            """,
            (client_id,),
        )
        row = cur.fetchone()
    return int(row[0] or 0) <= 1 if row else True


def _user_by_email_for_client(*, email: str, client_id: str) -> AuthUserRow | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, client_id, display_name, active, role
            FROM auth_users
            WHERE email = %s AND client_id = %s
            LIMIT 1;
            """,
            (email, client_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=str(row[5] or "developer"),
    )

def upsert_user(
    *,
    email: str,
    password: str,
    client_id: str | None = None,
    display_name: str | None = None,
) -> AuthUserRow:
    ensure_auth_schema()
    em = normalize_email(email)
    if not validate_email(em):
        raise ValueError("invalid_email")
    if not (password or "").strip():
        raise ValueError("empty_password")
    cid = (client_id or CENTRAL_DEFAULT_CLIENT_ID).strip() or CENTRAL_DEFAULT_CLIENT_ID
    pwd_hash = hash_password(password)
    uid = uuid.uuid4()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_users (id, email, password_hash, client_id, display_name, active)
                VALUES (%s, %s, %s, %s, %s, true)
                ON CONFLICT (email) DO UPDATE SET
                  password_hash = EXCLUDED.password_hash,
                  client_id = EXCLUDED.client_id,
                  display_name = COALESCE(EXCLUDED.display_name, auth_users.display_name),
                  active = true,
                  updated_at = now()
                RETURNING id, email, client_id, display_name, active;
                """,
                (uid, em, pwd_hash, cid, (display_name or "").strip() or None),
            )
            row = cur.fetchone()
    if not row:
        raise RuntimeError("upsert_failed")
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
    )


def create_admin_user(
    *,
    email: str,
    password: str,
    client_id: str | None = None,
    display_name: str | None = None,
    role: str | None = None,
) -> AuthUserRow:
    """Create/update a local user without granting operational memberships."""
    ensure_auth_schema()
    em = normalize_email(email)
    if not validate_email(em):
        raise ValueError("invalid_email")
    if not (password or "").strip():
        raise ValueError("empty_password")
    r = _normalize_auth_role(role, allow_legacy=False)
    cid = (client_id or CENTRAL_DEFAULT_CLIENT_ID).strip() or CENTRAL_DEFAULT_CLIENT_ID
    existing = _user_by_email_for_client(email=em, client_id=cid)
    if existing and _would_remove_last_active_admin(user_id=existing.id, client_id=cid, role=r, active=True):
        raise ValueError("last_admin")
    pwd_hash = hash_password(password)
    uid = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth_users (id, email, password_hash, client_id, display_name, active, role)
            VALUES (%s, %s, %s, %s, %s, true, %s)
            ON CONFLICT (email) DO UPDATE SET
              password_hash = EXCLUDED.password_hash,
              display_name = COALESCE(EXCLUDED.display_name, auth_users.display_name),
              active = true,
              role = EXCLUDED.role,
              updated_at = now()
            WHERE auth_users.client_id = EXCLUDED.client_id
            RETURNING id, email, client_id, display_name, active, role;
            """,
            (uid, em, pwd_hash, cid, (display_name or "").strip() or None, r),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("email_conflict")
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=str(row[5] or r),
    )


def list_auth_users(
    *,
    client_id: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[AuthUserRow]:
    ensure_auth_schema()
    cid = (client_id or "").strip()
    query = (q or "").strip().lower()
    clauses: list[str] = []
    params: list[object] = []
    if cid:
        clauses.append("client_id = %s")
        params.append(cid)
    if query:
        clauses.append("(lower(email) LIKE %s OR lower(COALESCE(display_name, '')) LIKE %s)")
        like = f"%{query[:120]}%"
        params.extend([like, like])
    params.append(max(1, min(500, int(limit))))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, email, client_id, display_name, active, role
            FROM auth_users
            {where}
            ORDER BY email ASC
            LIMIT %s;
            """,
            params,
        )
        rows = cur.fetchall()
    out: list[AuthUserRow] = []
    for row in rows:
        role = str(row[5] or "developer").strip().lower()
        if role not in (_AUTH_USER_ROLES | _AUTH_LEGACY_ROLES):
            role = "developer"
        out.append(
            AuthUserRow(
                id=str(row[0]),
                email=str(row[1]),
                client_id=str(row[2]),
                display_name=str(row[3] or ""),
                active=bool(row[4]),
                role=role,
            )
        )
    return out


def update_admin_user(
    *,
    user_id: str,
    client_id: str,
    display_name: str | None = None,
    role: str | None = None,
    active: bool | None = None,
) -> AuthUserRow | None:
    ensure_auth_schema()
    uid = (user_id or "").strip()
    cid = (client_id or "").strip()
    if not uid or not cid:
        raise ValueError("invalid_user")
    normalized_role = _normalize_auth_role(role, allow_legacy=False) if role is not None else None
    if _would_remove_last_active_admin(user_id=uid, client_id=cid, role=normalized_role, active=active):
        raise ValueError("last_admin")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth_users
            SET display_name = COALESCE(%s, display_name),
                role = COALESCE(%s, role),
                active = COALESCE(%s, active),
                updated_at = now()
            WHERE id = %s AND client_id = %s
            RETURNING id, email, client_id, display_name, active, role;
            """,
            (display_name, normalized_role, active, uid, cid),
        )
        row = cur.fetchone()
    if not row:
        return None
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=str(row[5] or "developer"),
    )


def reset_admin_user_password(*, user_id: str, client_id: str, password: str) -> bool:
    ensure_auth_schema()
    uid = (user_id or "").strip()
    cid = (client_id or "").strip()
    if not uid or not cid:
        raise ValueError("invalid_user")
    if not (password or "").strip():
        raise ValueError("empty_password")
    pwd_hash = hash_password(password)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth_users
            SET password_hash = %s,
                must_change_password = true,
                updated_at = now()
            WHERE id = %s AND client_id = %s
            RETURNING id;
            """,
            (pwd_hash, uid, cid),
        )
        return cur.fetchone() is not None


def change_user_password(*, user_id: str, current_password: str, new_password: str) -> AuthUserRow:
    """User changes own password; clears must_change_password."""
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("invalid_user")
    validate_new_password(new_password)
    user, pwd_hash = lookup_user_by_id_with_hash(uid)
    if user is None or pwd_hash is None:
        raise ValueError("user_not_found")
    if not user.active:
        raise ValueError("account_disabled")
    if not verify_password(current_password, pwd_hash):
        raise ValueError("invalid_current_password")
    if verify_password(new_password, pwd_hash):
        raise ValueError("password_unchanged")
    new_hash = hash_password(new_password)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth_users
            SET password_hash = %s,
                must_change_password = false,
                updated_at = now()
            WHERE id = %s
            RETURNING id, email, client_id, display_name, active, role, must_change_password;
            """,
            (new_hash, uid),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("user_not_found")
    return AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=str(row[5] or "developer"),
        must_change_password=bool(row[6]),
    )


def lookup_user_by_id_with_hash(user_id: str) -> tuple[AuthUserRow | None, str | None]:
    uid = (user_id or "").strip()
    if not uid:
        return None, None
    ensure_auth_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, client_id, display_name, active, password_hash, role, must_change_password
            FROM auth_users WHERE id = %s LIMIT 1;
            """,
            (uid,),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    role = str(row[6] or "developer").strip().lower()
    if role not in (_AUTH_USER_ROLES | _AUTH_LEGACY_ROLES):
        role = "developer"
    user = AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=role,
        must_change_password=bool(row[7]),
    )
    return user, str(row[5])


def set_user_role(*, email: str, role: str) -> bool:
    """Hardening A2 — set RBAC role for seeded / admin users."""
    em = normalize_email(email)
    r = _normalize_auth_role(role, allow_legacy=True)
    ensure_auth_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE auth_users SET role=%s, updated_at=now() WHERE email=%s RETURNING id",
            (r, em),
        )
        return cur.fetchone() is not None

def lookup_user_by_email(email: str) -> tuple[AuthUserRow | None, str | None]:
    """Retorna (user, password_hash) ou (None, None) se não existir."""
    em = normalize_email(email)
    if not validate_email(em):
        return None, None
    ensure_auth_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, client_id, display_name, active, password_hash, role, must_change_password
                FROM auth_users WHERE email = %s LIMIT 1;
                """,
                (em,),
            )
            row = cur.fetchone()
    if not row:
        return None, None
    role = str(row[6] or "developer").strip().lower()
    if role not in (_AUTH_USER_ROLES | _AUTH_LEGACY_ROLES):
        role = "developer"
    user = AuthUserRow(
        id=str(row[0]),
        email=str(row[1]),
        client_id=str(row[2]),
        display_name=str(row[3] or ""),
        active=bool(row[4]),
        role=role,
        must_change_password=bool(row[7]),
    )
    return user, str(row[5])

def verify_credentials(*, email: str, password: str) -> tuple[AuthUserRow | None, str | None]:
    """
    (user, None) em sucesso;
    (None, None) credenciais inválidas;
    (None, 'account_disabled') conta inactiva.
    """
    if not (password or ""):
        return None, None
    user, pwd_hash = lookup_user_by_email(email)
    if user is None or pwd_hash is None:
        return None, None
    if not user.active:
        return None, "account_disabled"
    if not verify_password(password, pwd_hash):
        return None, None
    return user, None

def auth_db_configured() -> bool:
    return bool((AUTH_USERS_DB_URL or "").strip()) and psycopg is not None and bcrypt is not None


# ═══ AUTH_LOGIN_RATE_LIMIT ═══

"""Rate limit in-process for POST /auth/login (Fase A)."""

_lock = threading.Lock()

_windows: dict[str, deque[float]] = {}

def _allow(key: str) -> tuple[bool, int | None]:
    window = float(_cfg.AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS)
    limit = int(_cfg.AUTH_LOGIN_RATE_LIMIT_PER_WINDOW)
    max_keys = int(_cfg.AUTH_LOGIN_RATE_LIMIT_MAX_KEYS)
    now = time.monotonic()
    k = (key or "_anon")[:256]

    with _lock:
        if k not in _windows and len(_windows) >= max_keys:
            _windows.pop(next(iter(_windows)))
        dq = _windows.setdefault(k, deque())
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            oldest = dq[0]
            retry_after = int(window - (now - oldest)) + 1
            return False, max(1, retry_after)
        dq.append(now)
        return True, None

def allow_login_attempt(*, client_ip: str, email: str) -> tuple[bool, int | None]:
    email_key = (email or "").strip().lower()[:128]
    ip_key = (client_ip or "").strip()[:64]
    ok_ip, ra_ip = _allow(f"ip:{ip_key}")
    if not ok_ip:
        return False, ra_ip
    return _allow(f"email:{email_key}")

def reset_login_rate_limit_for_tests() -> None:
    with _lock:
        _windows.clear()


# ═══ AUTH_PRODUCTION_POLICY ═══

"""Startup policy for auth/OIDC (ADR-015)."""

def _is_production() -> bool:
    return CENTRAL_APP_ENV in ("production", "prod")

def validate_auth_production_policy() -> None:
    """Fail fast on unsafe auth combinations in production."""
    if not _is_production():
        return

    if CENTRAL_JWT_MODE in ("hybrid", "oidc"):
        raise RuntimeError(
            "ADR-015: CENTRAL_JWT_MODE must be 'required' in production "
            "(hybrid/oidc are for staging and integrations only)."
        )

    if CENTRAL_JWT_MODE not in ("off", "optional", "required"):
        raise RuntimeError(f"Unknown CENTRAL_JWT_MODE: {CENTRAL_JWT_MODE}")

    if CENTRAL_JWT_MODE in ("optional", "required"):
        if not CENTRAL_OIDC_ENABLED:
            raise RuntimeError(
                "ADR-015: CENTRAL_OIDC_ENABLED is required in production when JWT is enabled."
            )
        if AUTH_LOGIN_ENABLED:
            raise RuntimeError(
                "ADR-015: AUTH_LOGIN_ENABLED must be 0 in production (OIDC-only login)."
            )


# ═══ REFRESH_REVOCATION_STORE ═══

"""Persist revoked refresh-token `jti` values until exp (rotation, Fase 4)."""

_lock = threading.Lock()

_MAX_ENTRIES = 8000

def _path() -> Path:
    from app.config import REFRESH_REVOCATIONS_STORE_PATH

    return Path(REFRESH_REVOCATIONS_STORE_PATH or "").expanduser()

def _load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"jtis": {}, "users": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jtis": {}, "users": {}}
    if not isinstance(raw, dict):
        return {"jtis": {}, "users": {}}
    jtis = raw.get("jtis")
    if not isinstance(jtis, dict):
        jtis = {}
    users = raw.get("users")
    if not isinstance(users, dict):
        users = {}
    return {"jtis": jtis, "users": users}

def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def _prune(jtis: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    out: dict[str, int] = {}
    for k, v in jtis.items():
        if not isinstance(k, str) or not k:
            continue
        try:
            exp = int(v)
        except (TypeError, ValueError):
            continue
        if exp > now:
            out[k] = exp
    if len(out) > _MAX_ENTRIES:
        # drop oldest by exp
        items = sorted(out.items(), key=lambda kv: kv[1])[-_MAX_ENTRIES // 2 :]
        out = dict(items)
    return out

def is_jti_revoked(jti: str) -> bool:
    with _lock:
        data = _load()
        jtis = data.get("jtis", {})
        if not isinstance(jtis, dict):
            return False
        exp = jtis.get(jti)
        if exp is None:
            return False
        try:
            return int(exp) > int(time.time())
        except (TypeError, ValueError):
            return False

def revoke_jti(jti: str, exp_unix: int) -> None:
    with _lock:
        data = _load()
        jtis = data.get("jtis", {})
        users = data.get("users", {})
        if not isinstance(jtis, dict):
            jtis = {}
        if not isinstance(users, dict):
            users = {}
        jtis = _prune(jtis)
        jtis[jti] = int(exp_unix)
        _save({"jtis": jtis, "users": users})


def is_refresh_subject_revoked(*, sub: str, iat_unix: int | None) -> bool:
    uid = (sub or "").strip()
    if not uid or iat_unix is None:
        return False
    with _lock:
        data = _load()
        users = data.get("users", {})
        if not isinstance(users, dict):
            return False
        revoked_after = users.get(uid)
        if revoked_after is None:
            return False
        try:
            return int(iat_unix) <= int(revoked_after)
        except (TypeError, ValueError):
            return False


def revoke_user_refresh_sessions(*, user_id: str, revoked_after_unix: int | None = None) -> None:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("invalid_user")
    with _lock:
        data = _load()
        jtis = data.get("jtis", {})
        users = data.get("users", {})
        if not isinstance(jtis, dict):
            jtis = {}
        if not isinstance(users, dict):
            users = {}
        users[uid] = int(revoked_after_unix or time.time())
        _save({"jtis": _prune(jtis), "users": users})
