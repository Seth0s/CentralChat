"""P3 Onda 2: POST /actions/os-power-reboot e os-power-shutdown validam approval + payload vazio."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient

import app.approvals_store as approvals_store
from app.server import app


class TestOsPowerActions(unittest.TestCase):
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

    def test_reboot_happy_path_double_confirm(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r1",
            "os.power.reboot",
            "P3",
            {},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_os_power_reboot") as mock_c:
            mock_c.return_value = {"result": "os_power_reboot_ok"}
            r = self.client.post(
                "/actions/os-power-reboot",
                json={"approval_id": rec["approval_id"]},
            )
        self.assertEqual(r.status_code, 200)
        mock_c.assert_called_once_with(ANY, rec["approval_id"], double_confirmation_ack=True)
        self.assertEqual(r.json().get("result"), "os_power_reboot_ok")

    def test_shutdown_happy_path(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r2",
            "os.power.shutdown",
            "P3",
            {},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_os_power_shutdown") as mock_c:
            mock_c.return_value = {"result": "os_power_shutdown_ok"}
            r = self.client.post(
                "/actions/os-power-shutdown",
                json={"approval_id": rec["approval_id"]},
            )
        self.assertEqual(r.status_code, 200)
        mock_c.assert_called_once_with(ANY, rec["approval_id"], double_confirmation_ack=True)

    def test_reboot_rejects_non_empty_payload(self) -> None:
        from app.approvals_store import approve_or_first_double_step, create_pending

        rec = create_pending(
            "r3",
            "os.power.reboot",
            "P3",
            {"note": "x"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        r = self.client.post(
            "/actions/os-power-reboot",
            json={"approval_id": rec["approval_id"]},
        )
        self.assertEqual(r.status_code, 403)

    def test_reboot_not_approved(self) -> None:
        from app.approvals_store import create_pending

        rec = create_pending(
            "r4",
            "os.power.reboot",
            "P3",
            {},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        r = self.client.post(
            "/actions/os-power-reboot",
            json={"approval_id": rec["approval_id"]},
        )
        self.assertEqual(r.status_code, 403)

    def test_reboot_wrong_action_id(self) -> None:
        from app.approvals_store import approve_or_first_double_step, create_pending

        rec = create_pending(
            "r5",
            "test.echo",
            "P0",
            {},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        r = self.client.post(
            "/actions/os-power-reboot",
            json={"approval_id": rec["approval_id"]},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
