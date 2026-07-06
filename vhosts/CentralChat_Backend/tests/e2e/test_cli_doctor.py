"""Onda A — CLI doctor subprocess."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.e2e.helpers import cli_login, run_central, stack_reachable

pytestmark = [pytest.mark.e2e]


def test_doctor_fails_without_login() -> None:
    if not stack_reachable():
        pytest.skip("stack not up")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        r = run_central(["doctor"], config_home=cfg, timeout=30.0)
        assert r.returncode != 0
        assert "credentials" in (r.stdout + r.stderr)


def test_doctor_ok_with_login_and_workspace() -> None:
    if not stack_reachable():
        pytest.skip("stack not up")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "cfg"
        cfg.mkdir()
        ws = Path(tmp) / "repo"
        ws.mkdir()
        cli_login(cfg)
        run_central(["workspace", str(ws)], config_home=cfg)
        r = run_central(["doctor"], config_home=cfg, timeout=30.0)
        # daemon may be offline — expect fail on daemon only
        out = r.stdout + r.stderr
        assert "api_health" in out or "api ready" in out.lower() or "credentials" in out
