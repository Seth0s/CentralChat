"""P3-4: POST /actions/os-packages-upgrade-all valida approval + payload vazio."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app.approvals_store as approvals_store
from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

app = None
TestClient = None
try:
    from fastapi.testclient import TestClient as _TestClient

    from app.server import app as _app

    TestClient = _TestClient
    app = _app
except ImportError:  # pragma: no cover
    pass


@unittest.skipUnless(app is not None, "FastAPI app + deps em falta")
class TestOsPackagesUpgradeAllAction(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        self._store_patch = patch.object(approvals_store, "APPROVALS_STORE_PATH", self.store_path)
        self._store_patch.start()
        assert TestClient is not None
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._store_patch.stop()
        os.unlink(self.store_path)

    def test_non_empty_stored_payload_403(self) -> None:
        rec = create_pending(
            "rid",
            "os.packages.upgrade_all",
            "P3",
            {"evil": 1},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        resp = self.client.post(
            "/actions/os-packages-upgrade-all",
            json={"approval_id": rec["approval_id"]},
        )
        self.assertEqual(resp.status_code, 403)

    def test_happy_path_mocks_system_agent(self) -> None:
        rec = create_pending(
            "rid",
            "os.packages.upgrade_all",
            "P3",
            {},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_os_packages_upgrade_all") as mock_call:
            mock_call.return_value = {
                "request_id": "rid",
                "action_id": "os.packages.upgrade_all",
                "result": "package_upgrade_all_ok",
            }
            resp = self.client.post(
                "/actions/os-packages-upgrade-all",
                json={"approval_id": rec["approval_id"]},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        mock_call.assert_called_once()
        kw = mock_call.call_args.kwargs
        self.assertTrue(kw.get("double_confirmation_ack"))


if __name__ == "__main__":
    unittest.main()
