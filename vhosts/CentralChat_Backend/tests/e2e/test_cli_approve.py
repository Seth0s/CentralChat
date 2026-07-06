"""B1.8 — E2E central approve via CLI."""

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


def test_cli_approve_after_patch(require_stack: None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        target = ws / "cli-approved.txt"
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-approve-cli-"))
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
                            "path": "cli-approved.txt",
                            "new_content": "via central approve\n",
                            "diff": "",
                            "summary": "1 file",
                            "change_kind": "write",
                        },
                    },
                    timeout=15.0,
                )
                create.raise_for_status()
                approval_id = create.json()["approval_id"]

                run_central(["approve", approval_id], config_home=cfg_home, timeout=30.0)
                assert wait_for_file(target, timeout=45.0), "daemon did not write after CLI approve"
                assert "via central approve" in target.read_text(encoding="utf-8")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
