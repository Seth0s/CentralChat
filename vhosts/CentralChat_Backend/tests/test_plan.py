import unittest

from pydantic import ValidationError

from app.plan import PlanStep, build_plan_text_chat, build_plan_voice_chat
from app.tool_registry import (
    iter_agent_tool_plan_specs,
    list_registered_tool_names,
    registered_tool_plan_kinds,
)


class TestPlanRegistrySync(unittest.TestCase):
    def test_registered_plan_kinds_match_iter_specs(self):
        kinds_from_iter = {t[0] for t in iter_agent_tool_plan_specs()}
        self.assertEqual(kinds_from_iter, registered_tool_plan_kinds())

    def test_plan_text_includes_tool_steps_from_registry(self):
        plan = build_plan_text_chat("rid-x")
        kinds = [s.kind for s in plan.steps]
        self.assertEqual(kinds[0], "infer")
        self.assertEqual(kinds[-1], "synthesize")
        self.assertIn("tool.host_summary", kinds)
        self.assertIn("tool.list_processes", kinds)
        self.assertIn("tool.list_process_tree", kinds)
        self.assertIn("tool.list_listening_sockets", kinds)
        self.assertIn("tool.create_approval_request", kinds)
        self.assertIn("tool.disable_systemd_user_unit", kinds)
        self.assertIn("tool.install_os_package", kinds)
        self.assertIn("tool.upgrade_os_packages_all", kinds)
        self.assertIn("tool.get_file_metadata", kinds)
        self.assertIn("tool.get_hardware_sensors", kinds)
        self.assertIn("tool.list_disk_partitions", kinds)
        self.assertIn("tool.list_disk_usage", kinds)
        self.assertIn("tool.list_network_interfaces", kinds)
        self.assertIn("tool.get_network_routes", kinds)
        self.assertIn("tool.get_central_stack_health", kinds)
        self.assertIn("tool.grep_workspace", kinds)
        self.assertIn("tool.list_network_connections", kinds)
        self.assertIn("tool.list_systemd_units", kinds)
        self.assertIn("tool.get_journal_tail", kinds)
        self.assertIn("tool.query_installed_packages", kinds)
        self.assertIn("tool.read_file_text", kinds)
        self.assertIn("tool.request_shell", kinds)
        self.assertIn("tool.open_browser_url", kinds)
        self.assertIn("tool.probe_network_endpoint", kinds)
        self.assertIn("tool.send_desktop_notification", kinds)
        self.assertIn("tool.write_config_file", kinds)
        self.assertIn("tool.mutate_external_file", kinds)
        # Ordem alfabética por nome da tool no registry (fonte de verdade: iter_agent_tool_plan_specs)
        tool_kinds = [k for k in kinds if k.startswith("tool.")]
        expected_tool_kinds = [t[0] for t in iter_agent_tool_plan_specs()]
        self.assertEqual(tool_kinds, expected_tool_kinds)

    def test_plan_voice_order(self):
        plan = build_plan_voice_chat("rid-y")
        kinds = [s.kind for s in plan.steps]
        self.assertEqual(kinds[:2], ["transcribe", "infer"])
        self.assertEqual(kinds[-1], "synthesize")

    def test_step_ids_sequential_strings(self):
        plan = build_plan_text_chat("r")
        ids = [s.step_id for s in plan.steps]
        self.assertEqual(ids, [str(i) for i in range(1, len(ids) + 1)])

    def test_plan_step_rejects_unknown_kind(self):
        with self.assertRaises(ValidationError):
            PlanStep(
                step_id="1",
                kind="tool.nonexistent",
                risk_hint="low",
                description="x",
            )

    def test_tool_steps_target_system_agent(self):
        plan = build_plan_text_chat("r")
        tool_steps = [s for s in plan.steps if s.kind.startswith("tool.")]
        self.assertTrue(tool_steps)
        kind_to_target = {t[0]: t[3] for t in iter_agent_tool_plan_specs()}
        for s in tool_steps:
            self.assertEqual(s.target, kind_to_target.get(s.kind))

    def test_plan_specs_count_matches_registry(self):
        self.assertEqual(
            len(iter_agent_tool_plan_specs()),
            len(list_registered_tool_names()),
        )


if __name__ == "__main__":
    unittest.main()
