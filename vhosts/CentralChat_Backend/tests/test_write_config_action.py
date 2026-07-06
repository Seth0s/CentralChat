"""P2-3: POST /actions/write-config-file valida approval + payload."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.approvals_store as approvals_store
from app.server import app


class TestWriteConfigAction(unittest.TestCase):
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

    def test_execute_happy_path(self) -> None:
        from app.approvals_store import create_pending

        rec = create_pending(
            "r1",
            "filesystem.path.write_config",
            "P2",
            {"path": "/tmp/a.yaml", "content": "k: 1\n", "create_backup": True},
            tenant_id="default",
        )
        from app.approvals_store import approve_or_first_double_step

        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_write_config_file") as mock_w:
            mock_w.return_value = {"result": "write_ok", "bytes_written": 5}
            r = self.client.post(
                "/actions/write-config-file",
                json={
                    "approval_id": rec["approval_id"],
                    "path": "/tmp/a.yaml",
                    "content": "k: 1\n",
                    "create_backup": True,
                },
            )
        self.assertEqual(r.status_code, 200)
        mock_w.assert_called_once()
        body = r.json()
        self.assertEqual(body.get("result"), "write_ok")

    def test_content_mismatch(self) -> None:
        from app.approvals_store import approve_or_first_double_step, create_pending

        rec = create_pending(
            "r2",
            "filesystem.path.write_config",
            "P2",
            {"path": "/tmp/b.yaml", "content": "a", "create_backup": False},
            tenant_id="default",
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        r = self.client.post(
            "/actions/write-config-file",
            json={
                "approval_id": rec["approval_id"],
                "path": "/tmp/b.yaml",
                "content": "b",
                "create_backup": False,
            },
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
