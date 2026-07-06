"""Onda C — enterprise wave unit tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.shared.cli_auth import _hash_api_key, validate_api_key
from app.shared.siem_outbox import build_siem_envelope
from app.integrations.git_service import _branch_name, _commit_message


class OndaCCliAuthTest(unittest.TestCase):
    def test_api_key_hash_stable(self) -> None:
        h1 = _hash_api_key("ck_test_key_123")
        h2 = _hash_api_key("ck_test_key_123")
        self.assertEqual(h1, h2)

    @patch("app.shared.cli_auth.memory_db_enabled", return_value=False)
    def test_validate_api_key_without_db(self, *_m: object) -> None:
        self.assertIsNone(validate_api_key("ck_short"))


class OndaCSiemTest(unittest.TestCase):
    def test_envelope_v1(self) -> None:
        env = build_siem_envelope(action="policy.violation", tenant_id="default", metadata={"x": 1})
        self.assertEqual(env["version"], "1")
        self.assertEqual(env["source"], "centralchat")
        self.assertEqual(env["action"], "policy.violation")


class OndaCGitTest(unittest.TestCase):
    def test_branch_naming(self) -> None:
        self.assertEqual(_branch_name("abcd1234-uuid"), "central/approval-abcd1234")

    def test_commit_message_trailer(self) -> None:
        rec = {
            "approval_id": "abcd1234-0000",
            "payload": {"path": "src/payment/foo.go"},
        }
        msg = _commit_message(rec)
        self.assertIn("central(approval:abcd1234)", msg)
        self.assertIn("foo.go", msg)


class OndaCComplianceTest(unittest.TestCase):
    def test_preview_returns_merged(self) -> None:
        from app.shared.compliance_packs import preview_compliance_pack

        with patch("app.shared.compliance_packs.get_tenant_config", return_value=None):
            prev = preview_compliance_pack("pci-dss")
        self.assertIsNotNone(prev)
        assert prev is not None
        self.assertIn("audit_ready_notice", prev)
        self.assertIn("merged_policies", prev)


class OndaCPrFailureTest(unittest.TestCase):
    @patch("app.integrations.pr_failure.create_work_item")
    @patch("app.integrations.pr_failure.append_audit_event")
    @patch("app.integrations.pr_failure._notify_webhooks")
    def test_handle_pr_failure_creates_wi(
        self, _wh: object, _audit: object, mock_wi: object
    ) -> None:
        mock_wi.return_value = {"id": "WI-1"}
        from app.integrations.pr_failure import handle_pr_failure

        out = handle_pr_failure(
            {"approval_id": "a1", "payload": {"path": "src/x.py"}},
            {"ok": False, "error": "github_pr_failed"},
            tenant_id="default",
        )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("work_item", {}).get("id"), "WI-1")


class OndaCGitIntegrationTest(unittest.TestCase):
    @patch("app.integrations.git_service._resolve_github_token", return_value=("tok", "pat"))
    @patch("app.integrations.git_service._tenant_git_config")
    def test_create_github_pr_ok(self, mock_cfg: object, *_m: object) -> None:
        mock_cfg.return_value = {
            "github": {"repo": "org/repo", "token": "tok"},
            "write_mode_default": "pr_only",
        }
        from app.integrations import git_service

        client_inst = MagicMock()
        client_ctx = MagicMock()
        client_ctx.__enter__ = MagicMock(return_value=client_inst)
        client_ctx.__exit__ = MagicMock(return_value=False)

        ref_resp = MagicMock(status_code=200)
        ref_resp.json.return_value = {"object": {"sha": "base_sha"}}
        missing_file = MagicMock(status_code=404)
        push_resp = MagicMock(status_code=200)
        push_resp.json.return_value = {"content": {}}
        branch_resp = MagicMock(status_code=201)
        pr_resp = MagicMock(status_code=201)
        pr_resp.json.return_value = {"html_url": "https://github.com/org/repo/pull/1", "number": 1}

        client_inst.get.side_effect = [ref_resp, missing_file]
        client_inst.post.side_effect = [branch_resp, pr_resp]
        client_inst.put.return_value = push_resp

        with patch.object(git_service.httpx, "Client", return_value=client_ctx):
            rec = {
                "approval_id": "abcd1234-uuid",
                "session_id": "s1",
                "action_id": "file.write",
                "payload": {"path": "src/foo.py", "new_content": "print(1)\n", "diff": "---\n+++"},
            }
            out = git_service.create_github_pr(approval_rec=rec, tenant_id="default")
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("pr_number"), 1)


if __name__ == "__main__":
    unittest.main()
