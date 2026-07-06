"""Onda A — audit events verifiable after auth flows."""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.helpers import DEFAULT_DEV_EMAIL, api_url, auth_headers, login

pytestmark = [pytest.mark.e2e]


def test_audit_lists_login_events(require_stack: None) -> None:
    login()
    bad = httpx.post(
        f"{api_url()}/auth/login",
        json={"email": DEFAULT_DEV_EMAIL, "password": "wrong-password-e2e"},
        timeout=10.0,
    )
    assert bad.status_code in (401, 403)

    auditor = login(email="auditor@local.test", password="changeme")
    tok = auditor["access_token"]
    r = httpx.get(
        f"{api_url()}/admin/audit/events",
        headers=auth_headers(tok),
        params={"action": "auth.login", "limit": 20},
        timeout=15.0,
    )
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    assert len(items) >= 1

    failed = httpx.get(
        f"{api_url()}/admin/audit/events",
        headers=auth_headers(tok),
        params={"action": "auth.login_failed", "limit": 10},
        timeout=15.0,
    )
    assert failed.status_code == 200
    assert (failed.json().get("count") or 0) >= 1

    export = httpx.get(
        f"{api_url()}/admin/audit/export",
        headers=auth_headers(tok),
        params={"format": "csv", "limit": 50},
        timeout=15.0,
    )
    assert export.status_code == 200
    assert "auth.login" in export.text or "action" in export.text.lower()
