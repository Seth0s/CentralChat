"""C1.5 — CLI auth: OAuth2-style device code + API keys."""

from __future__ import annotations

import hashlib
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

DEVICE_CODE_TTL_SECONDS = 600
DEVICE_POLL_INTERVAL_SECONDS = 5
_API_KEY_PREFIX = "ck_"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _user_code() -> str:
    part_a = "".join(secrets.choice(string.digits) for _ in range(4))
    part_b = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    return f"{part_a}-{part_b}"


def ensure_cli_auth_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS device_auth_codes (
                device_code TEXT PRIMARY KEY,
                user_code TEXT NOT NULL UNIQUE,
                client_label TEXT NOT NULL DEFAULT 'cli',
                status TEXT NOT NULL DEFAULT 'pending',
                sub TEXT,
                tenant_id TEXT,
                email TEXT,
                role TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ NOT NULL,
                approved_at TIMESTAMPTZ
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS api_keys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT 'cli',
                role TEXT NOT NULL DEFAULT 'developer',
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                revoked_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_used_at TIMESTAMPTZ
            );"""
        )


def start_device_flow(*, client_label: str = "cli") -> dict[str, Any]:
    ensure_cli_auth_schema()
    device_code = secrets.token_urlsafe(32)
    user_code = _user_code().upper()
    expires = _utc_now() + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO device_auth_codes (device_code, user_code, client_label, expires_at)
               VALUES (%s,%s,%s,%s)""",
            (device_code, user_code, (client_label or "cli")[:64], expires.isoformat()),
        )
    return {
        "device_code": device_code,
        "user_code": user_code,
        "expires_in": DEVICE_CODE_TTL_SECONDS,
        "interval": DEVICE_POLL_INTERVAL_SECONDS,
        "verification_uri": "/login",
    }


def approve_device_code(
    user_code: str,
    *,
    sub: str,
    tenant_id: str,
    email: str = "",
    role: str = "developer",
) -> bool:
    ensure_cli_auth_schema()
    code = (user_code or "").strip().upper()
    if not code or not sub or not tenant_id:
        return False
    now = _utc_now().isoformat()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE device_auth_codes
               SET status='approved', sub=%s, tenant_id=%s, email=%s, role=%s, approved_at=%s
               WHERE user_code=%s AND status='pending' AND expires_at > %s
               RETURNING device_code""",
            (sub.strip(), tenant_id.strip(), email[:320], role[:32], now, code, now),
        )
        return cur.fetchone() is not None


def poll_device_token(device_code: str) -> dict[str, Any]:
    ensure_cli_auth_schema()
    dc = (device_code or "").strip()
    if not dc:
        return {"error": "invalid_device_code"}
    now = _utc_now().isoformat()
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT status, sub, tenant_id, email, role, expires_at
               FROM device_auth_codes WHERE device_code=%s LIMIT 1""",
            (dc,),
        )
        row = cur.fetchone()
    if not row:
        return {"error": "invalid_device_code"}
    status, sub, tenant_id, email, role, expires_at = row
    if str(expires_at) < now and status == "pending":
        return {"error": "expired_token"}
    if status == "pending":
        return {"error": "authorization_pending"}
    if status != "approved" or not sub or not tenant_id:
        return {"error": "access_denied"}
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM device_auth_codes WHERE device_code=%s", (dc,))
    return {
        "sub": str(sub),
        "client_id": str(tenant_id),
        "email": str(email or ""),
        "role": str(role or "developer"),
    }


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(
    *,
    tenant_id: str,
    user_id: str,
    label: str = "cli",
    role: str = "developer",
) -> tuple[str, dict[str, Any]] | None:
    ensure_cli_auth_schema()
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    uid = (user_id or "").strip()
    if not uid:
        return None
    raw = _API_KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw[:12]
    key_hash = _hash_api_key(raw)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO api_keys (tenant_id, user_id, label, role, key_prefix, key_hash)
               VALUES (%s,%s,%s,%s,%s,%s)
               RETURNING id::text, created_at::text""",
            (tid, uid, (label or "cli")[:120], role[:32], prefix, key_hash),
        )
        row = cur.fetchone()
    if not row:
        return None
    return raw, {
        "id": str(row[0]),
        "tenant_id": tid,
        "user_id": uid,
        "label": label,
        "role": role,
        "key_prefix": prefix,
        "created_at": str(row[1]),
    }


def validate_api_key(raw_key: str) -> dict[str, Any] | None:
    ensure_cli_auth_schema()
    key = (raw_key or "").strip()
    if not key.startswith(_API_KEY_PREFIX) or len(key) < 20:
        return None
    key_hash = _hash_api_key(key)
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, user_id, role, label
               FROM api_keys WHERE key_hash=%s AND revoked_at IS NULL LIMIT 1""",
            (key_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("UPDATE api_keys SET last_used_at=now() WHERE key_hash=%s", (key_hash,))
    return {
        "key_id": str(row[0]),
        "client_id": str(row[1]),
        "sub": str(row[2]),
        "role": str(row[3] or "developer"),
        "label": str(row[4] or ""),
    }


def revoke_api_key(key_id: str, *, tenant_id: str | None = None) -> bool:
    ensure_cli_auth_schema()
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE api_keys SET revoked_at=now()
               WHERE id=%s::uuid AND tenant_id=%s AND revoked_at IS NULL
               RETURNING id""",
            (key_id.strip(), tid),
        )
        return cur.fetchone() is not None
