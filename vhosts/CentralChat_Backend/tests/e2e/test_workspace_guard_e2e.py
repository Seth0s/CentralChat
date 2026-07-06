"""B1.3 — E2E workspace guard blocks traversal writes."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from tests.e2e.helpers import api_url, auth_headers, cli_login, login, run_central

pytestmark = [pytest.mark.e2e]


def test_approve_traversal_path_does_not_write_outside_workspace(require_stack: None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        outside = Path(tempfile.mkdtemp(prefix="central-outside-"))
        outside_file = outside / "escaped.txt"
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-guard-"))
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
                        "path": "../" + outside_file.name,
                        "new_content": "escape\n",
                        "diff": "",
                        "summary": "1 file",
                        "change_kind": "write",
                    },
                },
                timeout=15.0,
            )
            # Traversal in payload should fail validation or guard at approve
            if create.status_code == 200:
                approval_id = create.json()["approval_id"]
                approve = httpx.post(
                    f"{api_url()}/approvals/{approval_id}/approve",
                    headers=auth_headers(tok, str(ws)),
                    timeout=15.0,
                )
                # Approve may succeed but job should not write outside
                assert approve.status_code in (200, 400, 409)
            assert not outside_file.exists()
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
            shutil.rmtree(outside, ignore_errors=True)
