"""OC-12 MVP: fetch HTTP GET com allowlist de hostname (uso dev). Ver ADR-010."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


def normalize_hostname(host: str) -> str:
    return host.strip().lower().rstrip(".")


def parse_host_allowlist(raw: str) -> frozenset[str]:
    return frozenset(normalize_hostname(p) for p in raw.split(",") if p.strip())


def validate_url_for_allowlist(url: str, allow: frozenset[str]) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported_scheme")
    if not parsed.hostname:
        raise ValueError("missing_host")
    host = normalize_hostname(parsed.hostname)
    if host not in allow:
        raise ValueError("host_not_allowed")


def fetch_web_dev(
    url: str,
    *,
    allow_hosts: frozenset[str],
    max_bytes: int,
    timeout: float,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not allow_hosts:
        raise ValueError("empty_allowlist")
    validate_url_for_allowlist(url, allow_hosts)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False)
        close_client = True
    try:
        r = client.get(url.strip())
        raw = r.content
        truncated = len(raw) > max_bytes
        chunk = raw[:max_bytes]
        text = chunk.decode("utf-8", errors="replace")
        ct = (r.headers.get("content-type") or "").split(";")[0].strip()
        return {
            "ok": True,
            "status_code": r.status_code,
            "content_type": ct,
            "text": text,
            "truncated": truncated,
            "bytes_returned": len(chunk),
        }
    finally:
        if close_client:
            client.close()
