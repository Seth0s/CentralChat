"""P3 Onda 6a: POST /actions/os-account-unix-useradd valida approval + username."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient

import app.approvals_store as approvals_store
from app.server import app


class TestOsAccountUnixUseraddAction(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        self._patch = patch.object(approvals_store, "APPROVALS_STORE_PATH", self.store_path)
        self._patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patch.stop()
        os.unlink(self.store_path)

    def test_happy_path_double_confirm(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r1",
            "os.account.unix_useradd",
            "P3",
            {"username": "svc_exemplo"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_os_account_unix_useradd") as mock_c:
            mock_c.return_value = {"result": "unix_useradd_ok", "username": "svc_exemplo"}
            r = self.client.post(
                "/actions/os-account-unix-useradd",
                json={"approval_id": rec["approval_id"], "username": "svc_exemplo"},
            )
        self.assertEqual(r.status_code, 200)
        mock_c.assert_called_once_with(
            ANY, "svc_exemplo", rec["approval_id"], double_confirmation_ack=True
        )

    def test_username_mismatch_403(self) -> None:
        from app.approvals_store import approve_or_first_double_step, create_pending

        rec = create_pending(
            "r2",
            "os.account.unix_useradd",
            "P3",
            {"username": "svc_exemplo"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        r = self.client.post(
            "/actions/os-account-unix-useradd",
            json={"approval_id": rec["approval_id"], "username": "outro_nome"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
