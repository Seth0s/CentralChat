"""Onda A — approval deny creates work item (H1b)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from tests.e2e.helpers import api_url, auth_headers, cli_login, login, run_central

pytestmark = [pytest.mark.e2e]


def test_deny_approval_creates_work_item(require_stack: None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        target = ws / "denied.txt"
        cfg_home = Path(tempfile.mkdtemp(prefix="central-e2e-deny-"))
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
                        "new_content": "should not run\n",
                        "diff": "",
                        "summary": "1 file",
                        "change_kind": "write",
                    },
                },
                timeout=15.0,
            )
            create.raise_for_status()
            approval_id = create.json()["approval_id"]

            deny = httpx.post(
                f"{api_url()}/approvals/{approval_id}/deny",
                headers=auth_headers(tok, str(ws)),
                json={"reason": "e2e policy review"},
                timeout=15.0,
            )
            deny.raise_for_status()
            body = deny.json()
            assert body.get("status") == "denied"
            work_item = body.get("work_item")
            if work_item:
                assert work_item.get("id")
            else:
                items = httpx.get(
                    f"{api_url()}/ui/work-items",
                    headers=auth_headers(tok),
                    timeout=10.0,
                )
                items.raise_for_status()
                data = items.json()
                if not data.get("work_items_enabled"):
                    pytest.skip("work_items disabled (memory_db off)")
                linked = [
                    it
                    for it in data.get("items") or []
                    if approval_id in (it.get("approval_ids") or [])
                ]
                assert linked, "expected work item linked to denied approval"
        finally:
            shutil.rmtree(cfg_home, ignore_errors=True)
