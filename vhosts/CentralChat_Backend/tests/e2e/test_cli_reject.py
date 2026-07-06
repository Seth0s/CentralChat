"""B1.9 — E2E central reject with persisted reason."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from tests.e2e.helpers import api_url, auth_headers, cli_login, login, run_central

pytestmark = [pytest.mark.e2e]


def test_cli_reject_persists_reason(require_stack: None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-reject-cli-"))
        reason = "e2e CLI reject motivo"
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
                        "path": "rejected.txt",
                        "new_content": "nope\n",
                        "diff": "",
                        "summary": "1 file",
                        "change_kind": "write",
                    },
                },
                timeout=15.0,
            )
            create.raise_for_status()
            approval_id = create.json()["approval_id"]

            run_central(
                ["reject", approval_id, "-m", reason],
                config_home=cfg_home,
                timeout=30.0,
            )

            listed = httpx.get(
                f"{api_url()}/approvals",
                headers=auth_headers(tok, str(ws)),
                params={"status": "denied"},
                timeout=15.0,
            )
            listed.raise_for_status()
            items = listed.json().get("items") or []
            match = [it for it in items if it.get("approval_id") == approval_id]
            assert match, "denied approval not listed"
            assert match[0].get("deny_reason") == reason
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
