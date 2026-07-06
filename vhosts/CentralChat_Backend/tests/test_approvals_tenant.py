"""ADR17-1 — approvals isolated per tenant_id."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from app.approvals_store import (
    create_pending,
    get_approval,
    list_approvals,
    resolve_tenant_id_for_store,
)
from app.tenant_context import set_tenant_context


class TestApprovalsTenantIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch("app.config.CENTRAL_ROOT", self.tmp.name)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_tenant_a_does_not_see_tenant_b(self) -> None:
        rec_a = create_pending(
            "r-a",
            "shell.exec",
            "P3",
            {"mode": "argv", "argv": ["true"]},
            tenant_id="tenant-a",
        )
        create_pending(
            "r-b",
            "shell.exec",
            "P3",
            {"mode": "argv", "argv": ["true"]},
            tenant_id="tenant-b",
        )
        self.assertEqual(rec_a.get("tenant_id"), "tenant-a")
        items_a = list_approvals("pending", tenant_id="tenant-a")
        items_b = list_approvals("pending", tenant_id="tenant-b")
        self.assertEqual(len(items_a), 1)
        self.assertEqual(len(items_b), 1)
        self.assertEqual(items_a[0]["approval_id"], rec_a["approval_id"])
        self.assertNotEqual(items_a[0]["approval_id"], items_b[0]["approval_id"])

    def test_get_approval_scoped_to_tenant(self) -> None:
        rec = create_pending(
            "r1",
            "process.signal",
            "P1",
            {"pid": 1},
            tenant_id="tenant-x",
        )
        self.assertIsNone(get_approval(rec["approval_id"], tenant_id="tenant-y"))
        found = get_approval(rec["approval_id"], tenant_id="tenant-x")
        assert found is not None
        self.assertEqual(found["tenant_id"], "tenant-x")

    def test_resolve_tenant_from_context(self) -> None:
        set_tenant_context(client_id="acme-corp", sub="user-1")
        self.assertEqual(resolve_tenant_id_for_store(), "acme-corp")
        set_tenant_context(client_id=None, sub=None)


class TestToolPolicyPlatformReject(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    def test_dispatch_platform_tool_denied(self) -> None:
        from app.tool_registry import TOOL_NAME_GET_HOST_SUMMARY, dispatch_tool

        out = dispatch_tool(TOOL_NAME_GET_HOST_SUMMARY, {}, "req-1", tenant_id="tenant-a")
        self.assertFalse(out.get("ok", True))
        self.assertEqual(out.get("error"), "platform_tool_disabled")
        self.assertIn("message_pt", out)


if __name__ == "__main__":
    unittest.main()
