"""Onda A — approval happy path with real daemon."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from tests.e2e.helpers import (
    api_url,
    auth_headers,
    cli_login,
    login,
    run_central,
    start_daemon,
    wait_for_file,
)

pytestmark = [pytest.mark.e2e]


def test_approval_write_file_with_daemon(require_stack: None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        target = ws / "e2e-out.txt"
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-cfg-"))
        try:
            cli_login(cfg_home)
            run_central(["workspace", str(ws)], config_home=cfg_home, timeout=30.0)
            proc = start_daemon(cfg_home)
            try:
                time.sleep(2.0)
                tok = login()["access_token"]

                create = httpx.post(
                    f"{api_url()}/approvals/test",
                    headers=auth_headers(tok, str(ws)),
                    json={
                        "action_id": "file.write",
                        "payload": {
                            "path": "e2e-out.txt",
                            "new_content": "e2e hello\n",
                            "diff": "",
                            "summary": "1 file",
                            "change_kind": "write",
                        },
                    },
                    timeout=15.0,
                )
                create.raise_for_status()
                approval_id = create.json()["approval_id"]

                approve = httpx.post(
                    f"{api_url()}/approvals/{approval_id}/approve",
                    headers=auth_headers(tok, str(ws)),
                    timeout=30.0,
                )
                approve.raise_for_status()
                body = approve.json()
                assert body.get("client_job_id") or body.get("client_job")

                assert wait_for_file(target, timeout=45.0), "daemon did not write file"
                assert "e2e hello" in target.read_text(encoding="utf-8")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
