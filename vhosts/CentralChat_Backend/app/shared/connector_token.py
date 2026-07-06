"""T11.8 — Short-lived tokens for connector inference.

VPS generates a short-lived JWT that the connector presents
when calling the inference endpoint. Valid for 30 seconds.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode


def _secret() -> bytes:
    import os

    raw = os.getenv("CENTRAL_CONNECTOR_TOKEN_SECRET", "")
    if raw:
        return raw.encode("utf-8")[:32].ljust(32, b"\x00")
    return hashlib.sha256(b"central-connector-default-secret").digest()


def generate_connector_token(tenant_id: str) -> str:
    """Generate a short-lived token valid for 30s. HMAC-SHA256 based."""
    payload = {
        "tenant_id": tenant_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 30,
        "jti": hashlib.sha256(str(time.monotonic()).encode()).hexdigest()[:12],
    }
    body = urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(_secret(), body.encode(), "sha256").hexdigest()[:32]
    return f"{body}.{signature}"


def verify_connector_token(token: str) -> dict | None:
    """Verify a connector token. Returns payload dict or None if invalid."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        body, signature = parts
        # Pad for base64
        padded = body + "=" * (4 - len(body) % 4) if len(body) % 4 else body
        expected = hmac.new(_secret(), body.encode(), "sha256").hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(urlsafe_b64decode(padded + "==="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
