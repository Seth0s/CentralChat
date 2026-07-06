"""Onda A — stack smoke (health, login, ready)."""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.helpers import DEFAULT_DEV_EMAIL, DEFAULT_DEV_PASSWORD, api_url, login

pytestmark = [pytest.mark.e2e]


def test_health(require_stack: None) -> None:
    r = httpx.get(f"{api_url()}/health", timeout=5.0)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health_ready_postgres(require_stack: None) -> None:
    r = httpx.get(f"{api_url()}/health/ready", timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") in ("ok", "degraded")
    pg = (body.get("checks") or {}).get("postgres") or {}
    assert pg.get("status") in ("ok", "disabled", "error")


def test_login_returns_tokens(require_stack: None) -> None:
    body = login()
    assert body.get("access_token")
    assert body.get("refresh_token")


def test_config_requires_auth_when_jwt_required(require_stack: None) -> None:
    cfg = httpx.get(f"{api_url()}/auth/public-config", timeout=5.0).json()
    if cfg.get("jwt_mode") != "required":
        pytest.skip("jwt_mode is not required on this stack")
    r = httpx.get(f"{api_url()}/config", timeout=5.0)
    assert r.status_code == 401


def test_login_and_config(require_stack: None) -> None:
    tok = login()["access_token"]
    r = httpx.get(
        f"{api_url()}/config",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=5.0,
    )
    assert r.status_code == 200


def test_refresh_rotation(require_stack: None) -> None:
    cfg = httpx.get(f"{api_url()}/auth/public-config", timeout=5.0).json()
    if not cfg.get("auth_refresh_enabled"):
        pytest.skip("refresh disabled")
    first = login()
    r = httpx.post(
        f"{api_url()}/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
        timeout=10.0,
    )
    assert r.status_code == 200, r.text
    second = r.json()
    assert second.get("access_token")
    assert second["access_token"] != first["access_token"]
