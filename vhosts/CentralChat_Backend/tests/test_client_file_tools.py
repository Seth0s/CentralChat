"""ADR17-7 — client_read_file / client_grep enqueue jobs."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.client_file_tools import (
    FILE_GREP_ACTION_ID,
    FILE_READ_ACTION_ID,
    build_grep_payload,
    build_read_payload,
    dispatch_client_grep,
    dispatch_client_read_file,
    validate_client_path,
)
from app.tool_catalog_policy import get_tool_execution_class, is_tool_exposed_to_llm
from app.tool_policy import classify_tool_call
from app.tool_registry import TOOL_NAME_CLIENT_GREP, TOOL_NAME_CLIENT_READ_FILE


class TestClientFilePayloads(unittest.TestCase):
    def test_validate_path_rejects_empty(self) -> None:
        self.assertEqual(validate_client_path(""), "path_required")

    def test_build_read_payload(self) -> None:
        body, err = build_read_payload({"path": "/home/u/proj/README.md", "max_bytes": 4096})
        self.assertIsNone(err)
        assert body is not None
        self.assertEqual(body["path"], "/home/u/proj/README.md")
        self.assertEqual(body["max_bytes"], 4096)

    def test_build_grep_payload(self) -> None:
        body, err = build_grep_payload(
            {"path": "/home/u/proj", "pattern": "TODO", "max_matches": 10}
        )
        self.assertIsNone(err)
        assert body is not None
        self.assertEqual(body["pattern"], "TODO")


class TestClientFileCatalog(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    def test_client_tools_exposed(self) -> None:
        self.assertEqual(get_tool_execution_class(TOOL_NAME_CLIENT_READ_FILE), "client")
        self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_CLIENT_READ_FILE))
        self.assertTrue(is_tool_exposed_to_llm(TOOL_NAME_CLIENT_GREP))


class TestClientFileDispatch(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.client_file_tools.connector_online_for_tenant", return_value=False)
    def test_offline_before_enqueue(self, _online: unittest.mock.MagicMock) -> None:
        out = dispatch_client_read_file(
            arguments={"path": "/tmp/x.txt"},
            request_id="req-off",
        )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "client_agent_offline")

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.client_file_tools.connector_online_for_tenant", return_value=True)
    @patch("app.client_file_tools.enqueue_client_file_job")
    def test_read_enqueues_job(
        self,
        mock_enqueue: unittest.mock.MagicMock,
        _online: unittest.mock.MagicMock,
    ) -> None:
        mock_enqueue.return_value = {"job_id": "j-read", "status": "queued"}
        out = dispatch_client_read_file(
            arguments={"path": "/home/u/a.txt"},
            request_id="req-read",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("status"), "job_queued")
        mock_enqueue.assert_called_once()
        _args, kwargs = mock_enqueue.call_args
        self.assertEqual(kwargs["action_id"], FILE_READ_ACTION_ID)

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.client_file_tools.connector_online_for_tenant", return_value=True)
    @patch("app.client_file_tools.enqueue_client_file_job")
    def test_grep_enqueues_job(
        self,
        mock_enqueue: unittest.mock.MagicMock,
        _online: unittest.mock.MagicMock,
    ) -> None:
        mock_enqueue.return_value = {"job_id": "j-grep", "status": "queued"}
        out = dispatch_client_grep(
            arguments={"path": "/home/u/proj", "pattern": "fixme"},
            request_id="req-grep",
        )
        self.assertTrue(out.get("ok"))
        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["action_id"], FILE_GREP_ACTION_ID)


class TestClientFilePolicy(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.tool_policy.connector_online_for_tenant", return_value=False)
    def test_policy_blocks_offline(self, _online: unittest.mock.MagicMock) -> None:
        res = classify_tool_call(TOOL_NAME_CLIENT_READ_FILE, {"path": "/x"}, "tenant-a")
        self.assertFalse(res.allowed)
        self.assertEqual(res.error_code, "client_agent_offline")


@unittest.skipUnless(
    os.path.isfile("/etc/hosts"),
    "needs local filesystem",
)
class TestConnectorHandlers(unittest.TestCase):
    def test_read_hosts_file(self) -> None:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "connector"
        sys.path.insert(0, str(root))
        from central_connector.handlers import execute_file_read

        out = execute_file_read({"path": "/etc/hosts", "max_bytes": 2048})
        self.assertTrue(out.get("ok"))
        self.assertIn("127.0.0.1", out.get("content", ""))


if __name__ == "__main__":
    unittest.main()
