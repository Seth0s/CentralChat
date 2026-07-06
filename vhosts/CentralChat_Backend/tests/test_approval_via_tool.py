"""Opcao B: criar aprovacao via tool."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import app.desktop_actions as desktop_actions
from app.approval_via_tool import create_approval_from_tool


class TestApprovalViaTool(unittest.TestCase):
    def test_rejects_extra_payload_keys(self) -> None:
        out = create_approval_from_tool(
            arguments={"action_id": "process.signal", "payload": {"pid": 9, "nope": 1}},
            request_id="r1",
        )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "payload_extra_fields")

    def test_rejects_unknown_action(self) -> None:
        out = create_approval_from_tool(
            arguments={"action_id": "exec", "payload": {}},
            request_id="r1",
        )
        self.assertFalse(out.get("ok"))

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_process_signal(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a1",
            "request_id": "r2",
            "action_id": "process.signal",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={"action_id": "process.signal", "payload": {"pid": 4242}},
            request_id="r2",
        )
        self.assertTrue(out.get("ok"))
        mock_create.assert_called_once()
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "process.signal")
        self.assertEqual(call_kw["payload"], {"pid": 4242, "signal": 15})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_read_external(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a2",
            "request_id": "r3",
            "action_id": "filesystem.path.read_external",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "filesystem.path.read_external",
                "payload": {"path": "/var/log/allowed/app.log"},
            },
            request_id="r3",
        )
        self.assertTrue(out.get("ok"))
        mock_create.assert_called_once()
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "filesystem.path.read_external")
        self.assertEqual(call_kw["payload"], {"path": "/var/log/allowed/app.log"})

    @patch.object(desktop_actions, "OPEN_URL_HOST_ALLOWLIST_RAW", "example.com")
    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_desktop_open_url(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-url",
            "request_id": "r-url",
            "action_id": "desktop.open_url",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "desktop.open_url",
                "payload": {"url": "https://example.com/x"},
            },
            request_id="r-url",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "desktop.open_url")
        self.assertEqual(call_kw["payload"]["url"], "https://example.com/x")

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_desktop_notify(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-n",
            "request_id": "r-n",
            "action_id": "desktop.notify",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "desktop.notify",
                "payload": {"body": "Ola", "title": "T"},
            },
            request_id="r-n",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["payload"]["body"], "Ola")
        self.assertEqual(call_kw["payload"]["title"], "T")

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_systemd_user_unit_disable(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-u",
            "request_id": "r-u",
            "action_id": "systemd.user.unit.disable",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "systemd.user.unit.disable",
                "payload": {"unit": "backup.timer"},
            },
            request_id="r-u",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "systemd.user.unit.disable")
        self.assertEqual(call_kw["payload"], {"unit": "backup.timer"})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_systemd_unit_enable(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-en",
            "request_id": "r-en",
            "action_id": "systemd.unit.enable",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "systemd.unit.enable",
                "payload": {"unit": "foo.service"},
            },
            request_id="r-en",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "systemd.unit.enable")
        self.assertEqual(call_kw["payload"], {"unit": "foo.service"})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_systemd_unit_disable_system(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-dis",
            "request_id": "r-dis",
            "action_id": "systemd.unit.disable",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "systemd.unit.disable",
                "payload": {"unit": "bar.service"},
            },
            request_id="r-dis",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "systemd.unit.disable")
        self.assertEqual(call_kw["payload"], {"unit": "bar.service"})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_firewall_rule_apply(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-fw",
            "request_id": "r-fw",
            "action_id": "network.firewall.rule.apply",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "network.firewall.rule.apply",
                "payload": {
                    "port": 443,
                    "protocol": "tcp",
                    "direction": "in",
                    "action": "deny",
                },
            },
            request_id="r-fw",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "network.firewall.rule.apply")
        self.assertEqual(
            call_kw["payload"],
            {"port": 443, "protocol": "tcp", "direction": "in", "action": "deny"},
        )

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_os_packages_install(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-p",
            "request_id": "r-p",
            "action_id": "os.packages.install",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "os.packages.install",
                "payload": {"package": "htop"},
            },
            request_id="r-p",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "os.packages.install")
        self.assertEqual(call_kw["payload"], {"package": "htop"})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_os_packages_upgrade_all(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-u",
            "request_id": "r-u",
            "action_id": "os.packages.upgrade_all",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={"action_id": "os.packages.upgrade_all", "payload": {}},
            request_id="r-u",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "os.packages.upgrade_all")
        self.assertEqual(call_kw["payload"], {})

    @patch("app.approval_via_tool.create_pending")
    @patch("app.approval_via_tool.write_orchestrator_audit")
    def test_creates_os_account_unix_useradd(self, _audit, mock_create) -> None:
        mock_create.return_value = {
            "approval_id": "a-uadd",
            "request_id": "r-uadd",
            "action_id": "os.account.unix_useradd",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "os.account.unix_useradd",
                "payload": {"username": "svc_exemplo"},
            },
            request_id="r-uadd",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "os.account.unix_useradd")
        self.assertEqual(call_kw["payload"], {"username": "svc_exemplo"})

    @patch("app.approval_via_tool.create_pending")
    def test_create_approval_shell_exec(self, mock_create: object) -> None:
        mock_create.return_value = {
            "approval_id": "a-shell",
            "action_id": "shell.exec",
            "status": "pending",
        }
        out = create_approval_from_tool(
            arguments={
                "action_id": "shell.exec",
                "payload": {
                    "mode": "argv",
                    "argv": ["ls", "/central"],
                    "intent": "listar central",
                    "timeout_sec": 30,
                },
            },
            request_id="r-shell",
        )
        self.assertTrue(out.get("ok"))
        call_kw = mock_create.call_args.kwargs
        self.assertEqual(call_kw["action_id"], "shell.exec")
        self.assertEqual(call_kw["payload"]["mode"], "argv")
        self.assertEqual(call_kw["payload"]["argv"], ["ls", "/central"])


if __name__ == "__main__":
    unittest.main()
