"""Onda A — daemon offline: approve queues job but file stays on disk."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from tests.e2e.helpers import api_url, auth_headers, cli_login, login, run_central

pytestmark = [pytest.mark.e2e]


def test_approve_without_daemon_does_not_write_file(require_stack: None) -> None:
    """Without central daemon running, approved file.write must not land on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        target = ws / "offline-out.txt"
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-offline-"))
        try:
            cli_login(cfg_home)
            run_central(["workspace", str(ws)], config_home=cfg_home, timeout=30.0)
            tok = login()["access_token"]

            create = httpx.post(
                f"{api_url()}/approvals/test",
                headers=auth_headers(tok, str(ws)),
                json={
                    "action_id": "file.write",
                    "payload": {
                        "path": str(target),
                        "new_content": "offline test\n",
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
            assert not target.is_file(), "file must not exist without daemon consuming the job"
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
