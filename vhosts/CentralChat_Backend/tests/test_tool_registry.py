import unittest
from unittest.mock import patch

from app.tool_registry import (
    TOOL_NAME_CREATE_APPROVAL_REQUEST,
    TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT,
    TOOL_NAME_INSTALL_OS_PACKAGE,
    TOOL_NAME_UPGRADE_OS_PACKAGES_ALL,
    TOOL_NAME_GET_FILE_METADATA,
    TOOL_NAME_GET_HARDWARE_SENSORS,
    TOOL_NAME_GET_HOST_SUMMARY,
    TOOL_NAME_GET_JOURNAL_TAIL,
    TOOL_NAME_GET_NETWORK_ROUTES,
    TOOL_NAME_GET_CENTRAL_STACK_HEALTH,
    TOOL_NAME_GREP_WORKSPACE,
    TOOL_NAME_LIST_DISK_PARTITIONS,
    TOOL_NAME_LIST_DISK_USAGE,
    TOOL_NAME_LIST_LISTENING_SOCKETS,
    TOOL_NAME_LIST_NETWORK_CONNECTIONS,
    TOOL_NAME_LIST_NETWORK_INTERFACES,
    TOOL_NAME_LIST_PROCESSES,
    TOOL_NAME_LIST_PROCESS_TREE,
    TOOL_NAME_LIST_SYSTEMD_UNITS,
    TOOL_NAME_MUTATE_EXTERNAL_FILE,
    TOOL_NAME_OPEN_BROWSER_URL,
    TOOL_NAME_PROBE_NETWORK_ENDPOINT,
    TOOL_NAME_QUERY_INSTALLED_PACKAGES,
    TOOL_NAME_READ_FILE_TEXT,
    TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
    TOOL_NAME_WRITE_CONFIG_FILE,
    dispatch_tool,
    is_registered_tool,
    validate_tool_arguments,
)


class TestToolRegistry(unittest.TestCase):
    def setUp(self) -> None:
        # Dispatch tests target the legacy platform catalog (pre-ADR17 tenant widget defaults).
        self._p_legacy = patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
        self._p_meta = patch("app.config.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", True)
        self._p_legacy.start()
        self._p_meta.start()

    def tearDown(self) -> None:
        self._p_meta.stop()
        self._p_legacy.stop()

    def test_known_tool_empty_args_ok(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_HOST_SUMMARY))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_HOST_SUMMARY, {}))

    def test_unknown_tool_not_registered(self) -> None:
        self.assertFalse(is_registered_tool("rm_rf_root"))
        self.assertIsNotNone(validate_tool_arguments("rm_rf_root", {}))

    def test_extra_property_rejected(self) -> None:
        err = validate_tool_arguments(TOOL_NAME_GET_HOST_SUMMARY, {"evil": True})
        self.assertIsNotNone(err)

    def test_dispatch_returns_dict(self) -> None:
        out = dispatch_tool(TOOL_NAME_GET_HOST_SUMMARY, {}, "test-req-id")
        self.assertIsInstance(out, dict)
        self.assertIn("request_id", out)

    def test_list_processes_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_PROCESSES))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESSES, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESSES, {"limit": 5}))

    def test_list_processes_limit_schema(self) -> None:
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESSES, {"limit": 0}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESSES, {"limit": 999}))

    @patch("app.tool_registry.fetch_process_list_for_tool")
    def test_dispatch_list_processes(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r1", "items": [], "total_processes_reported": 0}
        out = dispatch_tool(TOOL_NAME_LIST_PROCESSES, {"limit": 10}, "r1")
        self.assertEqual(out["total_processes_reported"], 0)
        mock_fetch.assert_called_once_with("r1", limit=10)

    def test_list_process_tree_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_PROCESS_TREE))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESS_TREE, {}))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_LIST_PROCESS_TREE, {"limit": 50, "max_depth": 4}),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESS_TREE, {"limit": 0}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_PROCESS_TREE, {"max_depth": 99}))

    @patch("app.tool_registry.fetch_process_tree_for_tool")
    def test_dispatch_list_process_tree(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r1a", "items": [], "total_processes_collected": 0}
        out = dispatch_tool(
            TOOL_NAME_LIST_PROCESS_TREE,
            {"limit": 30, "max_depth": 5},
            "r1a",
        )
        self.assertEqual(out["total_processes_collected"], 0)
        mock_fetch.assert_called_once_with("r1a", limit=30, max_depth=5)

    def test_list_listening_registered_and_schema(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_LISTENING_SOCKETS))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_LISTENING_SOCKETS, {}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_LISTENING_SOCKETS, {"limit": 0}))

    @patch("app.tool_registry.fetch_listening_sockets_for_tool")
    def test_dispatch_list_listening(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r2", "items": [], "total_listeners": 0}
        out = dispatch_tool(TOOL_NAME_LIST_LISTENING_SOCKETS, {"limit": 50}, "r2")
        self.assertEqual(out["total_listeners"], 0)
        mock_fetch.assert_called_once_with("r2", limit=50)

    def test_get_file_metadata_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_FILE_METADATA))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_FILE_METADATA, {"path": "x"}))

    @patch("app.tool_registry.fetch_file_metadata_for_tool")
    def test_dispatch_get_file_metadata(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r3", "exists": True}
        out = dispatch_tool(TOOL_NAME_GET_FILE_METADATA, {"path": "state/x.json"}, "r3")
        self.assertTrue(out.get("exists"))
        mock_fetch.assert_called_once_with("r3", rel_path="state/x.json")

    def test_get_hardware_sensors_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_HARDWARE_SENSORS))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_HARDWARE_SENSORS, {}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_GET_HARDWARE_SENSORS, {"x": 1}))

    @patch("app.tool_registry.fetch_hardware_sensors_for_tool")
    def test_dispatch_get_hardware_sensors(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "rh", "battery": {"status": "ok"}}
        out = dispatch_tool(TOOL_NAME_GET_HARDWARE_SENSORS, {}, "rh")
        self.assertEqual(out.get("battery", {}).get("status"), "ok")
        mock_fetch.assert_called_once_with("rh")

    def test_list_disk_usage_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_DISK_USAGE))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_USAGE, {}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_USAGE, {"x": 1}))

    @patch("app.tool_registry.fetch_disk_usage_for_tool")
    def test_dispatch_list_disk_usage(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r5", "items": [{"path": "/", "total_bytes": 1}]}
        out = dispatch_tool(TOOL_NAME_LIST_DISK_USAGE, {}, "r5")
        self.assertEqual(len(out.get("items", [])), 1)
        mock_fetch.assert_called_once_with("r5")

    def test_list_disk_partitions_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_DISK_PARTITIONS))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {"limit": 10}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {"limit": 0}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {"limit": 129}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_DISK_PARTITIONS, {"x": 1}))

    @patch("app.tool_registry.fetch_disk_partitions_for_tool")
    def test_dispatch_list_disk_partitions(self, mock_fetch) -> None:
        mock_fetch.return_value = {
            "request_id": "r5p",
            "items": [{"device": "/dev/sda1", "mountpoint": "/", "fstype": "ext4", "opts": "rw"}],
            "truncated": False,
            "total_seen": 1,
        }
        out = dispatch_tool(TOOL_NAME_LIST_DISK_PARTITIONS, {"limit": 32}, "r5p")
        self.assertEqual(out.get("total_seen"), 1)
        mock_fetch.assert_called_once_with("r5p", limit=32)

    def test_grep_workspace_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GREP_WORKSPACE))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_GREP_WORKSPACE, {}))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_GREP_WORKSPACE,
                {"path": "/central", "pattern": "foo", "max_matches": 10},
            )
        )

    @patch("app.tool_registry.fetch_workspace_grep_for_tool")
    def test_dispatch_grep_workspace(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "rg1", "ok": True, "match_count": 1, "matches": []}
        out = dispatch_tool(
            TOOL_NAME_GREP_WORKSPACE,
            {"path": "/central/state", "pattern": "test", "max_matches": 40},
            "rg1",
        )
        self.assertTrue(out.get("ok"))
        mock_fetch.assert_called_once_with(
            "rg1",
            path="/central/state",
            pattern="test",
            max_matches=40,
        )

    def test_list_network_interfaces_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_NETWORK_INTERFACES))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_NETWORK_INTERFACES, {}))

    @patch("app.tool_registry.fetch_network_interfaces_for_tool")
    def test_dispatch_list_network_interfaces(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r6", "items": [], "total_interfaces": 0}
        out = dispatch_tool(TOOL_NAME_LIST_NETWORK_INTERFACES, {}, "r6")
        self.assertEqual(out.get("total_interfaces"), 0)
        mock_fetch.assert_called_once_with("r6")

    def test_get_network_routes_schema(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_NETWORK_ROUTES))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_NETWORK_ROUTES, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_NETWORK_ROUTES, {"limit": 50}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_GET_NETWORK_ROUTES, {"limit": 0}))

    @patch("app.tool_registry.fetch_network_routes_for_tool")
    def test_dispatch_get_network_routes(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r7", "items": []}
        out = dispatch_tool(TOOL_NAME_GET_NETWORK_ROUTES, {"limit": 16}, "r7")
        self.assertIn("items", out)
        mock_fetch.assert_called_once_with("r7", limit=16)

    def test_get_central_stack_health_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_CENTRAL_STACK_HEALTH))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_GET_CENTRAL_STACK_HEALTH, {}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_GET_CENTRAL_STACK_HEALTH, {"x": 1}))

    @patch("app.tool_registry.collect_central_stack_health")
    def test_dispatch_get_central_stack_health(self, mock_c) -> None:
        mock_c.return_value = {"request_id": "r7b", "services": {}, "summary": {}}
        out = dispatch_tool(TOOL_NAME_GET_CENTRAL_STACK_HEALTH, {}, "r7b")
        self.assertIn("services", out)
        mock_c.assert_called_once_with("r7b")

    def test_list_network_connections_schema(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_NETWORK_CONNECTIONS))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_NETWORK_CONNECTIONS, {}))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_LIST_NETWORK_CONNECTIONS,
                {"limit": 50, "state": "ALL_ACTIVE"},
            )
        )
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_LIST_NETWORK_CONNECTIONS, {"state": "LISTEN"})
        )

    @patch("app.tool_registry.fetch_network_connections_for_tool")
    def test_dispatch_list_network_connections(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r8", "items": [], "total_matched": 0}
        out = dispatch_tool(
            TOOL_NAME_LIST_NETWORK_CONNECTIONS,
            {"limit": 20, "state": "ESTABLISHED"},
            "r8",
        )
        self.assertEqual(out.get("total_matched"), 0)
        mock_fetch.assert_called_once_with("r8", limit=20, state="ESTABLISHED")

    def test_list_systemd_units_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_LIST_SYSTEMD_UNITS))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {}))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {"limit": 50}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {"limit": 0}))
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_LIST_SYSTEMD_UNITS, {"x": 1}))

    @patch("app.tool_registry.fetch_systemd_units_for_tool")
    def test_dispatch_list_systemd_units(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "r9", "items": [], "total_units_reported": 0}
        out = dispatch_tool(TOOL_NAME_LIST_SYSTEMD_UNITS, {"limit": 20}, "r9")
        self.assertEqual(out["total_units_reported"], 0)
        mock_fetch.assert_called_once_with("r9", limit=20)

    def test_get_journal_tail_schema(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_GET_JOURNAL_TAIL))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_GET_JOURNAL_TAIL, {"unit": "nginx.service"}),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_GET_JOURNAL_TAIL,
                {"identifier": "sshd", "since": "24h", "max_bytes": 4096},
            ),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_GET_JOURNAL_TAIL, {}))
        self.assertIsNotNone(
            validate_tool_arguments(
                TOOL_NAME_GET_JOURNAL_TAIL,
                {"unit": "a", "identifier": "b"},
            ),
        )

    @patch("app.tool_registry.fetch_journal_tail_for_tool")
    def test_dispatch_get_journal_tail(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "rj", "text": "ok"}
        out = dispatch_tool(
            TOOL_NAME_GET_JOURNAL_TAIL,
            {"unit": "svc.service", "since": "1h"},
            "rj",
        )
        self.assertEqual(out.get("text"), "ok")
        mock_fetch.assert_called_once_with(
            "rj",
            unit="svc.service",
            identifier=None,
            since="1h",
            max_bytes=16384,
        )

    def test_query_packages_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_QUERY_INSTALLED_PACKAGES))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_QUERY_INSTALLED_PACKAGES, {"package": "bash"}),
        )
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_QUERY_INSTALLED_PACKAGES, {}),
        )

    @patch("app.tool_registry.fetch_packages_query_for_tool")
    def test_dispatch_query_packages(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "rp", "lines": ["bash\t1"]}
        out = dispatch_tool(TOOL_NAME_QUERY_INSTALLED_PACKAGES, {"package": "bash"}, "rp")
        self.assertEqual(out["lines"], ["bash\t1"])
        mock_fetch.assert_called_once_with("rp", package="bash")

    def test_read_file_text_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_READ_FILE_TEXT))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_READ_FILE_TEXT, {"path": "state/x.json"}),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_READ_FILE_TEXT,
                {"path": "state/x.json", "max_bytes": 4096},
            ),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_READ_FILE_TEXT, {}))
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_READ_FILE_TEXT, {"max_bytes": 512}),
        )
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_READ_FILE_TEXT, {"path": "x", "max_bytes": 100}),
        )

    @patch("app.tool_registry.fetch_read_file_text_for_tool")
    def test_dispatch_read_file_text(self, mock_fetch) -> None:
        mock_fetch.return_value = {"request_id": "rr", "content": "hi"}
        out = dispatch_tool(
            TOOL_NAME_READ_FILE_TEXT,
            {"path": "state/a.txt", "max_bytes": 2048},
            "rr",
        )
        self.assertEqual(out.get("content"), "hi")
        mock_fetch.assert_called_once_with("rr", rel_path="state/a.txt", max_bytes=2048)

    def test_create_approval_schema_ok(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_CREATE_APPROVAL_REQUEST))
        args = {"action_id": "process.signal", "payload": {"pid": 42}}
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args))
        args_ext = {
            "action_id": "filesystem.path.read_external",
            "payload": {"path": "/var/log/x.log"},
        }
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_ext))
        args_url = {"action_id": "desktop.open_url", "payload": {"url": "https://x.example/"}}
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_url))
        args_nv = {"action_id": "desktop.notify", "payload": {"body": "hi"}}
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_nv))
        args_probe = {
            "action_id": "network.endpoint.probe",
            "payload": {"host": "127.0.0.1", "port": 80, "kind": "tcp"},
        }
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_probe))
        args_ud = {
            "action_id": "systemd.user.unit.disable",
            "payload": {"unit": "backup.timer"},
        }
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_ud))
        args_wc = {
            "action_id": "filesystem.path.write_config",
            "payload": {"path": "/central/state/x.txt", "content": "x", "create_backup": False},
        }
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_wc))
        args_pkg = {"action_id": "os.packages.install", "payload": {"package": "htop"}}
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_CREATE_APPROVAL_REQUEST, args_pkg))

    def test_disable_systemd_user_unit_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "x.timer"}),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {}))
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "svc.service"}),
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_disable_systemd_user_unit(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "ru"}
        out = dispatch_tool(TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT, {"unit": "sync.timer"}, "ru")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={"action_id": "systemd.user.unit.disable", "payload": {"unit": "sync.timer"}},
            request_id="ru",
        )

    def test_install_os_package_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_INSTALL_OS_PACKAGE))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "htop"}),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_INSTALL_OS_PACKAGE, {}))
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "bad name"}),
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_install_os_package(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rp"}
        out = dispatch_tool(TOOL_NAME_INSTALL_OS_PACKAGE, {"package": "vim-enhanced"}, "rp")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={"action_id": "os.packages.install", "payload": {"package": "vim-enhanced"}},
            request_id="rp",
        )

    def test_upgrade_os_packages_all_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_UPGRADE_OS_PACKAGES_ALL))
        self.assertIsNone(validate_tool_arguments(TOOL_NAME_UPGRADE_OS_PACKAGES_ALL, {}))
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_UPGRADE_OS_PACKAGES_ALL, {"x": 1}),
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_upgrade_os_packages_all(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "ru"}
        out = dispatch_tool(TOOL_NAME_UPGRADE_OS_PACKAGES_ALL, {}, "ru")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={"action_id": "os.packages.upgrade_all", "payload": {}},
            request_id="ru",
        )

    def test_write_config_file_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_WRITE_CONFIG_FILE))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_WRITE_CONFIG_FILE,
                {"path": "/central/config/a.yaml", "content": "k: 1\n"},
            ),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_WRITE_CONFIG_FILE, {}))
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_WRITE_CONFIG_FILE, {"path": "/x", "content": "a", "create_backup": 1}),
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_write_config_file(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rw"}
        out = dispatch_tool(
            TOOL_NAME_WRITE_CONFIG_FILE,
            {"path": "/central/state/t.txt", "content": "body\n", "create_backup": False},
            "rw",
        )
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={
                "action_id": "filesystem.path.write_config",
                "payload": {"path": "/central/state/t.txt", "content": "body\n", "create_backup": False},
            },
            request_id="rw",
        )

    def test_mutate_external_file_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_MUTATE_EXTERNAL_FILE))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_MUTATE_EXTERNAL_FILE,
                {"operation": "delete", "src_path": "/central/state/x.txt"},
            ),
        )
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_MUTATE_EXTERNAL_FILE,
                {"operation": "copy", "src_path": "/a", "dst_path": "/b"},
            ),
        )
        self.assertIsNotNone(
            validate_tool_arguments(TOOL_NAME_MUTATE_EXTERNAL_FILE, {"operation": "delete"}),
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_mutate_external_file_delete(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rm"}
        out = dispatch_tool(
            TOOL_NAME_MUTATE_EXTERNAL_FILE,
            {"operation": "delete", "src_path": "/central/state/z.txt"},
            "rm",
        )
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={
                "action_id": "filesystem.path.mutate_external",
                "payload": {"operation": "delete", "src_path": "/central/state/z.txt"},
            },
            request_id="rm",
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_mutate_external_file_copy(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rc"}
        out = dispatch_tool(
            TOOL_NAME_MUTATE_EXTERNAL_FILE,
            {"operation": "copy", "src_path": "/central/a.txt", "dst_path": "/central/b.txt"},
            "rc",
        )
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={
                "action_id": "filesystem.path.mutate_external",
                "payload": {
                    "operation": "copy",
                    "src_path": "/central/a.txt",
                    "dst_path": "/central/b.txt",
                },
            },
            request_id="rc",
        )

    def test_open_browser_url_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_OPEN_BROWSER_URL))
        self.assertIsNone(
            validate_tool_arguments(TOOL_NAME_OPEN_BROWSER_URL, {"url": "https://example.com/"}),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_OPEN_BROWSER_URL, {}))

    def test_send_desktop_notification_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_SEND_DESKTOP_NOTIFICATION))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
                {"body": "x", "title": "y"},
            ),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_SEND_DESKTOP_NOTIFICATION, {}))

    def test_probe_network_endpoint_registered(self) -> None:
        self.assertTrue(is_registered_tool(TOOL_NAME_PROBE_NETWORK_ENDPOINT))
        self.assertIsNone(
            validate_tool_arguments(
                TOOL_NAME_PROBE_NETWORK_ENDPOINT,
                {"host": "127.0.0.1", "port": 8080, "kind": "http", "path": "/health"},
            ),
        )
        self.assertIsNotNone(validate_tool_arguments(TOOL_NAME_PROBE_NETWORK_ENDPOINT, {}))

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_create_approval(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "r4"}
        args = {"action_id": "systemd.unit.restart", "payload": {"unit": "a.service"}}
        out = dispatch_tool(TOOL_NAME_CREATE_APPROVAL_REQUEST, args, "r4")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(arguments=args, request_id="r4")

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_create_approval_systemd_p3_enable(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "r5"}
        args = {"action_id": "systemd.unit.enable", "payload": {"unit": "x.service"}}
        out = dispatch_tool(TOOL_NAME_CREATE_APPROVAL_REQUEST, args, "r5")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(arguments=args, request_id="r5")

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_open_browser_url(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rb"}
        out = dispatch_tool(TOOL_NAME_OPEN_BROWSER_URL, {"url": "https://a.test/"}, "rb")
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={"action_id": "desktop.open_url", "payload": {"url": "https://a.test/"}},
            request_id="rb",
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_send_desktop_notification(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rn"}
        out = dispatch_tool(
            TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
            {"body": "msg", "title": "sub"},
            "rn",
        )
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={
                "action_id": "desktop.notify",
                "payload": {"body": "msg", "title": "sub"},
            },
            request_id="rn",
        )

    @patch("app.tool_registry.create_approval_from_tool")
    def test_dispatch_probe_network_endpoint(self, mock_c) -> None:
        mock_c.return_value = {"ok": True, "request_id": "rp"}
        out = dispatch_tool(
            TOOL_NAME_PROBE_NETWORK_ENDPOINT,
            {"host": "model-router", "port": 8005, "kind": "tcp"},
            "rp",
        )
        self.assertTrue(out.get("ok"))
        mock_c.assert_called_once_with(
            arguments={
                "action_id": "network.endpoint.probe",
                "payload": {"host": "model-router", "port": 8005, "kind": "tcp"},
            },
            request_id="rp",
        )
