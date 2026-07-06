"""
Fase I+ — fuzz / casos em massa: deny-by-default, schema, parse JSON (sem hypothesis).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.tool_loop import parse_agent_tool_response, run_agent_tool_flow
from app.tool_registry import (
    TOOL_NAME_CREATE_APPROVAL_REQUEST,
    TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT,
    TOOL_NAME_INSTALL_OS_PACKAGE,
    TOOL_NAME_UPGRADE_OS_PACKAGES_ALL,
    TOOL_NAME_OPEN_BROWSER_URL,
    TOOL_NAME_PROBE_NETWORK_ENDPOINT,
    TOOL_NAME_GET_FILE_METADATA,
    TOOL_NAME_GET_HARDWARE_SENSORS,
    TOOL_NAME_GET_HOST_SUMMARY,
    TOOL_NAME_GET_JOURNAL_TAIL,
    TOOL_NAME_GET_NETWORK_ROUTES,
    TOOL_NAME_GET_CENTRAL_STACK_HEALTH,
    TOOL_NAME_LIST_DISK_PARTITIONS,
    TOOL_NAME_LIST_DISK_USAGE,
    TOOL_NAME_LIST_LISTENING_SOCKETS,
    TOOL_NAME_LIST_NETWORK_CONNECTIONS,
    TOOL_NAME_LIST_NETWORK_INTERFACES,
    TOOL_NAME_LIST_PROCESSES,
    TOOL_NAME_LIST_PROCESS_TREE,
    TOOL_NAME_LIST_SYSTEMD_UNITS,
    TOOL_NAME_QUERY_INSTALLED_PACKAGES,
    TOOL_NAME_READ_FILE_TEXT,
    TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
    TOOL_NAME_MUTATE_EXTERNAL_FILE,
    TOOL_NAME_WRITE_CONFIG_FILE,
    validate_tool_arguments,
)


def _audit_sink() -> tuple[list[dict], object]:
    events: list[dict] = []

    def _a(ev: dict) -> None:
        events.append(ev)

    return events, _a


def _malicious_tool_names() -> list[str]:
    """Nomes que nunca devem passar o registry (exact match deny-by-default)."""
    return [
        "",
        " ",
        "exec",
        "eval",
        "__import__",
        "os.system",
        "subprocess",
        "shell",
        "bash",
        "curl",
        "wget",
        "http.get",
        "POST",
        "capabilities/system.summary",
        "/capabilities/process.list",
        "systemd.unit.restart",
        "systemd.unit.stop",
        "systemd.unit.enable",
        "systemd.unit.disable",
        "os.power.reboot",
        "os.power.shutdown",
        "network.firewall.policy.apply",
        "os.account.unix_useradd",
        "filesystem.path.write_config",
        "filesystem.path.mutate_external",
        "process.signal",
        "network.listen.sockets",
        "get_host_summaries",
        "getHostSummary",
        "GET_HOST_SUMMARY",
        "\u200bget_host_summary",
        "get_host_summary\u0000",
        "../../../etc/passwd",
        "..\\..\\windows",
        "file.read",
        "vault.read",
        "create_approval_requests",
        "rm -rf /",
        "'; DROP TABLE--",
        "<script>",
        "{{7*7}}",
        "list_processes" + "A",
        "list_processes"[:-1],
        "a" * 300,
        "🔧get_host_summary",
    ]


def _invalid_argument_payloads() -> list[tuple[str, dict]]:
    """(tool_name, args) esperados como invalidos pelo jsonschema."""
    out: list[tuple[str, dict]] = []
    for tool, cap in (
        (TOOL_NAME_LIST_PROCESSES, 200),
        (TOOL_NAME_LIST_LISTENING_SOCKETS, 500),
    ):
        out.extend(
            [
                (tool, {"limit": 0}),
                (tool, {"limit": -1}),
                (tool, {"limit": cap + 1}),
                (tool, {"limit": 999999}),
                (tool, {"limit": "40"}),
                (tool, {"limit": 40.5}),
                (tool, {"limit": None}),
                (tool, {"limit": True}),
                (tool, {"extra": 1}),
                (tool, {"limit": 10, "evil": 0}),
            ]
        )
    out.append((TOOL_NAME_GET_HOST_SUMMARY, {"x": 1}))
    out.append((TOOL_NAME_GET_HOST_SUMMARY, {"limit": 1}))
    out.append((TOOL_NAME_GET_HARDWARE_SENSORS, {"x": 1}))
    out.append((TOOL_NAME_GET_CENTRAL_STACK_HEALTH, {"x": 1}))
    out.append((TOOL_NAME_LIST_DISK_USAGE, {"x": 1}))
    out.append((TOOL_NAME_LIST_DISK_PARTITIONS, {"x": 1}))
    for bad in (
        {"limit": 0},
        {"limit": 129},
        {"limit": "1"},
        {"evil": 1},
    ):
        out.append((TOOL_NAME_LIST_DISK_PARTITIONS, bad))
    out.append((TOOL_NAME_LIST_NETWORK_INTERFACES, {"x": 1}))
    for tool, cap in ((TOOL_NAME_GET_NETWORK_ROUTES, 100),):
        out.extend(
            [
                (tool, {"limit": 0}),
                (tool, {"limit": cap + 1}),
                (tool, {"limit": "10"}),
                (tool, {"evil": 1}),
            ]
        )
    out.extend(
        [
            (TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"limit": 0}),
            (TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"limit": 501}),
            (TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"state": "LISTEN"}),
            (TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"state": 1}),
            (TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"extra": 1}),
        ]
    )
    for bad in (
        {"limit": 0},
        {"limit": 201},
        {"limit": "1"},
        {"evil": 1},
    ):
        out.append((TOOL_NAME_LIST_SYSTEMD_UNITS, bad))
    out.extend(
        [
            (TOOL_NAME_LIST_PROCESS_TREE, {"limit": 0}),
            (TOOL_NAME_LIST_PROCESS_TREE, {"limit": 201}),
            (TOOL_NAME_LIST_PROCESS_TREE, {"max_depth": 0}),
            (TOOL_NAME_LIST_PROCESS_TREE, {"max_depth": 33}),
            (TOOL_NAME_LIST_PROCESS_TREE, {"limit": 10, "max_depth": "2"}),
            (TOOL_NAME_LIST_PROCESS_TREE, {"extra": 1}),
        ]
    )
    out.extend(
        [
            (TOOL_NAME_GET_JOURNAL_TAIL, {}),
            (TOOL_NAME_GET_JOURNAL_TAIL, {"unit": "a", "identifier": "b"}),
            (TOOL_NAME_GET_JOURNAL_TAIL, {"identifier": "x", "since": "nope"}),
            (TOOL_NAME_GET_JOURNAL_TAIL, {"unit": "u", "max_bytes": 100}),
            (TOOL_NAME_QUERY_INSTALLED_PACKAGES, {}),
            (TOOL_NAME_QUERY_INSTALLED_PACKAGES, {"package": ""}),
            (TOOL_NAME_QUERY_INSTALLED_PACKAGES, {"package": "x", "evil": 1}),
            (TOOL_NAME_GET_FILE_METADATA, {}),
            (TOOL_NAME_GET_FILE_METADATA, {"path": ""}),
            (TOOL_NAME_GET_FILE_METADATA, {"path": "/abs", "x": 1}),
            (TOOL_NAME_READ_FILE_TEXT, {}),
            (TOOL_NAME_READ_FILE_TEXT, {"path": ""}),
            (TOOL_NAME_READ_FILE_TEXT, {"path": "x", "max_bytes": 100}),
            (TOOL_NAME_READ_FILE_TEXT, {"path": "x", "max_bytes": 70000}),
            (TOOL_NAME_READ_FILE_TEXT, {"path": "x", "evil": 1}),
            (TOOL_NAME_CREATE_APPROVAL_REQUEST, {}),
            (TOOL_NAME_CREATE_APPROVAL_REQUEST, {"action_id": "process.signal"}),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "process.signal", "payload": {"pid": 1}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.restart", "payload": {"unit": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.stop", "payload": {"unit": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.enable", "payload": {"unit": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.disable", "payload": {"unit": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.power.reboot", "payload": {"evil": 1}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.power.shutdown", "payload": {"x": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.user.unit.disable", "payload": {"unit": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.user.unit.disable", "payload": {"unit": "a.service"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "network.firewall.rule.apply",
                    "payload": {"port": 443, "protocol": "tcp", "direction": "in", "evil": 1},
                },
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "network.firewall.rule.apply",
                    "payload": {"port": 0, "protocol": "tcp", "direction": "in", "action": "allow"},
                },
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "network.firewall.policy.apply", "payload": {"operation": "reload", "zone": "x"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "network.firewall.policy.apply", "payload": {"operation": "set_default_zone"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.account.unix_useradd", "payload": {"username": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.account.unix_useradd", "payload": {"username": "Root"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.account.unix_useradd", "payload": {"username": "1bad"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.account.unix_useradd", "payload": {"username": "ok", "evil": 1}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.read_external", "payload": {"path": "relative"}},
            ),
            (TOOL_NAME_CREATE_APPROVAL_REQUEST, {"action_id": "filesystem.path.read_external", "payload": {}}),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.read_external", "payload": {"path": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.write_config", "payload": {"path": "/x", "content": "a", "evil": 1}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.write_config", "payload": {"path": "relative", "content": "a"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.write_config", "payload": {"path": "/x"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "filesystem.path.write_config", "payload": {}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "process.signal", "payload": {"pid": 3, "extra": 1}},
            ),
            (TOOL_NAME_OPEN_BROWSER_URL, {}),
            (TOOL_NAME_OPEN_BROWSER_URL, {"url": ""}),
            (TOOL_NAME_OPEN_BROWSER_URL, {"url": "x", "extra": 1}),
            (TOOL_NAME_SEND_DESKTOP_NOTIFICATION, {}),
            (TOOL_NAME_SEND_DESKTOP_NOTIFICATION, {"body": "", "title": "x"}),
            (TOOL_NAME_SEND_DESKTOP_NOTIFICATION, {"body": "a", "evil": 1}),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "desktop.open_url", "payload": {"url": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "desktop.notify", "payload": {"body": ""}},
            ),
            (TOOL_NAME_PROBE_NETWORK_ENDPOINT, {}),
            (TOOL_NAME_PROBE_NETWORK_ENDPOINT, {"host": "", "port": 80, "kind": "tcp"}),
            (TOOL_NAME_PROBE_NETWORK_ENDPOINT, {"host": "x", "port": 0, "kind": "tcp"}),
            (TOOL_NAME_PROBE_NETWORK_ENDPOINT, {"host": "x", "port": 80, "kind": "udp"}),
            (TOOL_NAME_PROBE_NETWORK_ENDPOINT, {"host": "x", "port": 80, "kind": "tcp", "evil": 1}),
            (TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {}),
            (TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": ""}),
            (TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "svc.service"}),
            (TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "x.timer", "evil": 1}),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "filesystem.path.mutate_external",
                    "payload": {"operation": "delete", "src_path": "/x", "dst_path": "/y"},
                },
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "filesystem.path.mutate_external",
                    "payload": {"operation": "copy", "src_path": "/x"},
                },
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "filesystem.path.mutate_external",
                    "payload": {"operation": "rename", "src_path": "/x", "dst_path": "/y"},
                },
            ),
            (TOOL_NAME_MUTATE_EXTERNAL_FILE, {"operation": "delete", "src_path": "/x", "dst_path": "/y"}),
            (TOOL_NAME_MUTATE_EXTERNAL_FILE, {"operation": "copy", "src_path": "/x"}),
            (TOOL_NAME_MUTATE_EXTERNAL_FILE, {"operation": "move", "src_path": "rel", "dst_path": "/b"}),
            (TOOL_NAME_MUTATE_EXTERNAL_FILE, {"operation": "copy", "src_path": "/a", "dst_path": "/b", "evil": 1}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {"path": "/x"}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {"path": "rel", "content": "a"}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {"path": "/x", "content": "a", "create_backup": "yes"}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {"path": "/x", "content": "a", "evil": 1}),
            (TOOL_NAME_WRITE_CONFIG_FILE, {"path": "/x", "content": "x" * 32769}),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.packages.install", "payload": {"package": ""}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.packages.install", "payload": {"package": "bad pkg"}},
            ),
            (
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.packages.upgrade_all", "payload": {"x": 1}},
            ),
            (TOOL_NAME_UPGRADE_OS_PACKAGES_ALL, {"x": 1}),
            (TOOL_NAME_INSTALL_OS_PACKAGE, {}),
            (TOOL_NAME_INSTALL_OS_PACKAGE, {"package": ""}),
            (TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "a b"}),
            (TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "htop", "evil": 1}),
        ]
    )
    return out


class TestRegistryArgumentFuzz(unittest.TestCase):
    def test_validate_tool_arguments_rejects_fuzz_matrix(self) -> None:
        for tool, args in _invalid_argument_payloads():
            with self.subTest(tool=tool, args=args):
                err = validate_tool_arguments(tool, args)
                self.assertIsNotNone(
                    err,
                    f"expected rejection for {tool} {args!r}",
                )

    def test_known_good_arguments_accepted(self) -> None:
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_HOST_SUMMARY, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_HARDWARE_SENSORS, {}))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_LIST_PROCESSES, {"limit": 40}),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_LIST_LISTENING_SOCKETS, {"limit": 1}),
        )
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_USAGE, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {"limit": 128}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_NETWORK_INTERFACES, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_NETWORK_ROUTES, {"limit": 10}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_CENTRAL_STACK_HEALTH, {}))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_LIST_NETWORK_CONNECTIONS,
                {"limit": 10, "state": "ALL_ACTIVE"},
            )
        )
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {}))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {"limit": 100}),
        )
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESS_TREE, {}))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_LIST_PROCESS_TREE,
                {"limit": 100, "max_depth": 8},
            )
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_GET_JOURNAL_TAIL, {"unit": "nginx.service"}),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_GET_JOURNAL_TAIL, {"identifier": "sshd"}),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_QUERY_INSTALLED_PACKAGES, {"package": "bash"}),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_READ_FILE_TEXT, {"path": "state/x.txt"}),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_READ_FILE_TEXT,
                {"path": "config/app.yaml", "max_bytes": 1024},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_OPEN_BROWSER_URL, {"url": "https://example.com/"}),
        )
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_SEND_DESKTOP_NOTIFICATION, {"body": "ok"}),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_PROBE_NETWORK_ENDPOINT,
                {"host": "127.0.0.1", "port": 443, "kind": "tcp"},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "filesystem.path.read_external",
                    "payload": {"path": "/var/log/allowed/app.log"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "desktop.open_url",
                    "payload": {"url": "https://example.com/"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "desktop.notify", "payload": {"body": "hi"}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "systemd.unit.stop",
                    "payload": {"unit": "central-orchestrator.service"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.enable", "payload": {"unit": "foo.service"}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.unit.disable", "payload": {"unit": "bar.service"}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "systemd.user.unit.disable", "payload": {"unit": "backup.timer"}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "network.firewall.rule.apply",
                    "payload": {
                        "port": 443,
                        "protocol": "tcp",
                        "direction": "in",
                        "action": "allow",
                    },
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "network.firewall.policy.apply",
                    "payload": {"operation": "reload"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "network.firewall.policy.apply",
                    "payload": {"operation": "set_default_zone", "zone": "public"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.packages.install", "payload": {"package": "htop"}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {"action_id": "os.packages.upgrade_all", "payload": {}},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "os.account.unix_useradd",
                    "payload": {"username": "svc_exemplo"},
                },
            ),
        )
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "tzdata"}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_UPGRADE_OS_PACKAGES_ALL, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "x.socket"}))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_WRITE_CONFIG_FILE,
                {"path": "/central/state/x.txt", "content": "hello", "create_backup": True},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_WRITE_CONFIG_FILE,
                {"path": "/central/config/app.yaml", "content": "k: v\n"},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_CREATE_APPROVAL_REQUEST,
                {
                    "action_id": "filesystem.path.write_config",
                    "payload": {"path": "/central/state/t.txt", "content": "ok"},
                },
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_MUTATE_EXTERNAL_FILE,
                {"operation": "delete", "src_path": "/central/audit/x.log"},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_MUTATE_EXTERNAL_FILE,
                {
                    "operation": "move",
                    "src_path": "/central/state/a.txt",
                    "dst_path": "/central/config/b.txt",
                },
            ),
        )


class TestParseAgentToolResponseFuzz(unittest.TestCase):
    def test_malformed_or_tricky_json(self) -> None:
        cases: list[tuple[str, bool, int]] = [
            ("", False, 0),
            ("not json", False, 0),
            ("{", False, 0),
            ("[]", False, 0),
            ('{"final": "ok"}', True, 0),
            ('{"final": "ok", "tool_calls": null}', True, 0),
            ('{"final": "ok", "tool_calls": {}}', True, 0),
            ('{"final": "ok", "tool_calls": "nope"}', True, 0),
            ('{"final": "ok", "tool_calls": [{"name": "x"}]}', True, 1),
            (
                '{"final": null, "tool_calls": [null, {"name": "a", "arguments": {}}]}',
                True,
                1,
            ),
            (
                "```json\n"
                + '{"final": null, "tool_calls": [{"name": "t", "arguments": {}}]}'
                + "\n```",
                True,
                1,
            ),
        ]
        for raw, ok, n_calls in cases:
            with self.subTest(raw=raw[:60]):
                final, calls, json_ok = parse_agent_tool_response(raw)
                self.assertEqual(json_ok, ok, msg=raw[:200])
                if ok:
                    self.assertEqual(len(calls), n_calls)


class TestToolLoopDispatchFuzz(unittest.TestCase):
    def test_matrix_unknown_names_never_dispatch(self) -> None:
        for name in _malicious_tool_names():
            payload = {
                "final": None,
                "tool_calls": [{"name": name, "arguments": {}}],
            }
            llm_out = json.dumps(payload, ensure_ascii=False)
            events, audit = _audit_sink()
            with patch("app.tool_loop.call_llm", return_value=llm_out), patch(
                "app.tool_loop.dispatch_tool"
            ) as disp:
                _, meta = run_agent_tool_flow(
                    user_text="fuzz",
                    base_history=[],
                    request_id="fuzz-dispatch",
                    profile="balanced",
                    max_tool_executions=2,
                    audit=audit,
                )
                disp.assert_not_called()
            self.assertEqual(meta.get("mode"), "tool_denied", msg=repr(name[:80]))
            denied = [e for e in events if e.get("event") == "tool_denied"]
            self.assertEqual(len(denied), 1, msg=repr(name[:80]))
            self.assertEqual(
                denied[0].get("reason"),
                "unknown_or_disallowed_tool",
            )


if __name__ == "__main__":
    unittest.main()
