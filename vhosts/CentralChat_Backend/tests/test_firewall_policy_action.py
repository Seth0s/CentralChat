"""P3 Onda 5: POST /actions/firewall-policy-apply valida approval + payload."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient

import app.approvals_store as approvals_store
from app.server import app


class TestFirewallPolicyAction(unittest.TestCase):
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

    def test_reload_happy_path(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r1",
            "network.firewall.policy.apply",
            "P3",
            {"operation": "reload"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_firewall_policy_apply") as mock_c:
            mock_c.return_value = {"result": "firewall_policy_ok", "operation": "reload"}
            r = self.client.post(
                "/actions/firewall-policy-apply",
                json={"approval_id": rec["approval_id"], "operation": "reload"},
            )
        self.assertEqual(r.status_code, 200)
        mock_c.assert_called_once_with(
            ANY, "reload", rec["approval_id"], zone=None, double_confirmation_ack=True
        )

    def test_set_zone_happy_path(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r2",
            "network.firewall.policy.apply",
            "P3",
            {"operation": "set_default_zone", "zone": "public"},
            tenant_id="default",
            requires_double_confirmation=True,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        confirm_double(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_firewall_policy_apply") as mock_c:
            mock_c.return_value = {"result": "firewall_policy_ok"}
            r = self.client.post(
                "/actions/firewall-policy-apply",
                json={"approval_id": rec["approval_id"], "operation": "set_default_zone", "zone": "public"},
            )
        self.assertEqual(r.status_code, 200)
        mock_c.assert_called_once_with(
            ANY, "set_default_zone", rec["approval_id"], zone="public", double_confirmation_ack=True
        )

    def test_reload_zone_mismatch(self) -> None:
        from app.approvals_store import approve_or_first_double_step, confirm_double, create_pending

        rec = create_pending(
            "r3",
            "network.firewall.policy.apply",
            "P3",
            {"operation": "reload"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        r = self.client.post(
            "/actions/firewall-policy-apply",
            json={"approval_id": rec["approval_id"], "operation": "reload", "zone": "public"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
