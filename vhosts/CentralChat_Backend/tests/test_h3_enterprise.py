"""H3 — enterprise differentiation tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.audit_report import build_audit_report, export_audit_report_json, export_audit_report_pdf
from app.shared.compliance_packs import apply_compliance_pack, get_compliance_pack, list_compliance_packs
from app.default_tools import dispatch_exec_plan, TOOL_NAME_READ_FILE


class H3CompliancePackTest(unittest.TestCase):
    def test_lists_three_packs(self) -> None:
        packs = list_compliance_packs()
        ids = {p["id"] for p in packs}
        self.assertIn("pci-dss", ids)
        self.assertIn("lgpd-dev", ids)
        self.assertIn("iso27001", ids)

    def test_pci_pack_has_payment_dual(self) -> None:
        pack = get_compliance_pack("pci-dss")
        assert pack is not None
        repos = pack.get("policies", {}).get("repos", [])
        payment = [r for r in repos if "payment" in str(r.get("pattern", ""))]
        self.assertTrue(payment)
        self.assertEqual(payment[0].get("approval"), "dual")

    @patch("app.shared.compliance_packs.upsert_tenant_config")
    @patch("app.shared.compliance_packs.get_tenant_config")
    @patch("app.shared.compliance_packs.append_audit_event")
    def test_apply_merges_policies(
        self,
        _audit: unittest.mock.MagicMock,
        mock_get: unittest.mock.MagicMock,
        mock_upsert: unittest.mock.MagicMock,
    ) -> None:
        from app.tenant import TenantConfig

        mock_get.return_value = TenantConfig(
            tenant_id="acme",
            rate_limit_per_window=60,
            rate_limit_window_seconds=60,
            features_json={"policies": {"repos": [{"pattern": "**/custom/**", "write": "denied"}]}},
        )
        result = apply_compliance_pack("iso27001", tenant_id="acme")
        assert result is not None
        self.assertEqual(result["pack_id"], "iso27001")
        mock_upsert.assert_called_once()
        policies = result["policies"]
        patterns = [r.get("pattern") for r in policies.get("repos", [])]
        self.assertIn("**/custom/**", patterns)
        self.assertIn("**/api/**", patterns)


class H3AuditReportTest(unittest.TestCase):
    @patch("app.audit_report.list_audit_events")
    def test_path_prefix_filter(self, mock_list: unittest.mock.MagicMock) -> None:
        mock_list.return_value = [
            {"id": "1", "action": "tool.invoke", "resource": "read_file", "metadata": {"path": "payment/foo.py"}},
            {"id": "2", "action": "tool.invoke", "resource": "read_file", "metadata": {"path": "src/bar.py"}},
        ]
        report = build_audit_report(since="7d", path_prefix="payment/")
        self.assertEqual(report["summary"]["total_events"], 1)

    @patch("app.audit_report.list_audit_events")
    def test_pdf_starts_with_header(self, mock_list: unittest.mock.MagicMock) -> None:
        mock_list.return_value = [{"id": "1", "action": "session.turn", "created_at": "2026-01-01T00:00:00Z"}]
        report = build_audit_report(since="7d")
        pdf = export_audit_report_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        j = export_audit_report_json(report)
        self.assertIn("summary", j)


class H3ExecPlanTest(unittest.TestCase):
    @patch("app.default_tools.dispatch_default_tool")
    @patch("app.shared.policy_engine.evaluate_tool_policy")
    @patch("app.audit_service.append_audit_event")
    def test_exec_plan_runs_steps(
        self,
        _audit: unittest.mock.MagicMock,
        mock_pol: unittest.mock.MagicMock,
        mock_dispatch: unittest.mock.MagicMock,
    ) -> None:
        from app.shared.policy_engine import EnginePolicyResult

        mock_pol.return_value = EnginePolicyResult(allowed=True)
        mock_dispatch.return_value = {"ok": True, "content": "file"}
        out = dispatch_exec_plan(
            {
                "steps": [
                    {"tool": TOOL_NAME_READ_FILE, "arguments": {"path": "/tmp/a.txt"}},
                ],
            },
            "req-1",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["steps_run"], 1)
        mock_dispatch.assert_called_once()

    @patch("app.shared.policy_engine.evaluate_tool_policy")
    @patch("app.audit_service.append_audit_event")
    def test_exec_plan_stops_on_policy_denial(
        self,
        _audit: unittest.mock.MagicMock,
        mock_pol: unittest.mock.MagicMock,
    ) -> None:
        from app.shared.policy_engine import EnginePolicyResult

        mock_pol.return_value = EnginePolicyResult(
            allowed=False,
            error_code="policy_path_denied",
            message_pt="negado",
        )
        out = dispatch_exec_plan(
            {
                "steps": [{"tool": "read_file", "arguments": {"path": "/secret"}}],
                "stop_on_error": True,
            },
            "req-2",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(len(out["results"]), 1)


class H3BreakGlassPolicyTest(unittest.TestCase):
    @patch("app.shared.policy_engine._break_glass_bypass")
    @patch("app.shared.policy_engine._load_tenant_policies")
    def test_path_denied_uses_break_glass(
        self,
        mock_load: unittest.mock.MagicMock,
        mock_bg: unittest.mock.MagicMock,
    ) -> None:
        from app.shared.policy_engine import EnginePolicyResult, evaluate_path_policy

        mock_load.return_value = {
            "repos": [{"pattern": "credentials/secret.env", "read": "denied", "write": "denied"}],
        }
        mock_bg.return_value = EnginePolicyResult(allowed=True)
        res = evaluate_path_policy("credentials/secret.env", mode="read", tenant_id="default")
        self.assertTrue(res.allowed)
        mock_bg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
