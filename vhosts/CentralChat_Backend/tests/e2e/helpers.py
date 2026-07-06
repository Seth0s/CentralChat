"""Onda A — e2e helpers (live stack + CLI subprocess)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API = "http://127.0.0.1:8004"
DEFAULT_DEV_EMAIL = "dev@local.test"
DEFAULT_DEV_PASSWORD = "changeme"

_login_cache: dict[str, dict[str, Any]] = {}


def api_url() -> str:
    return os.getenv("E2E_API_URL", DEFAULT_API).rstrip("/")


def stack_reachable() -> bool:
    if os.getenv("SKIP_E2E", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        r = httpx.get(f"{api_url()}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def central_bin() -> str:
    explicit = os.getenv("E2E_CENTRAL_BIN", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    candidates = [
        Path(__file__).resolve().parents[3] / "CentralChat_CLI" / "central",
        Path(__file__).resolve().parents[2] / ".." / "CentralChat_CLI" / "central",
    ]
    for c in candidates:
        if c.is_file():
            return str(c.resolve())
    built = shutil.which("central")
    if built:
        return built
    raise FileNotFoundError("central binary not found — run: cd vhosts/CentralChat_CLI && go build -o central ./cmd/central")


def login(email: str = DEFAULT_DEV_EMAIL, password: str = DEFAULT_DEV_PASSWORD) -> dict[str, Any]:
    cache_key = f"{email}:{password}"
    if cache_key in _login_cache:
        return _login_cache[cache_key]
    r = httpx.post(
        f"{api_url()}/auth/login",
        json={"email": email, "password": password},
        timeout=15.0,
    )
    r.raise_for_status()
    body = r.json()
    _login_cache[cache_key] = body
    return body


def auth_headers(token: str, workspace: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if workspace:
        h["X-Central-Workspace"] = workspace
    return h


def run_central(
    args: list[str],
    *,
    config_home: Path,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    full_env["XDG_CONFIG_HOME"] = str(config_home)
    full_env["CENTRAL_API_URL"] = api_url()
    return subprocess.run(
        [central_bin(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
        check=False,
    )


def cli_login(config_home: Path, email: str = DEFAULT_DEV_EMAIL, password: str = DEFAULT_DEV_PASSWORD) -> None:
    r = run_central(
        ["login", "--email", email, "--password", password, "--api", api_url()],
        config_home=config_home,
    )
    if r.returncode != 0:
        raise RuntimeError(f"central login failed: {r.stderr or r.stdout}")


def start_daemon(config_home: Path) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(config_home)
    env["CENTRAL_API_URL"] = api_url()
    return subprocess.Popen(
        [central_bin(), "daemon"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def wait_for_file(path: Path, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.25)
    return False
