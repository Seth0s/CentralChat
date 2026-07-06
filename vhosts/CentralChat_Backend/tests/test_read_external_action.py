"""P1-3: POST /actions/read-external-file valida approval + path."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app.approvals_store as approvals_store
from app.approvals_store import approve_or_first_double_step, create_pending

app = None
TestClient = None
try:
    from fastapi.testclient import TestClient as _TestClient

    from app.server import app as _app

    TestClient = _TestClient
    app = _app
except ImportError:  # pragma: no cover - deps opcionais no host minimal
    pass


@unittest.skipUnless(app is not None, "FastAPI app + deps (ex.: prometheus_client) em falta")
class TestReadExternalAction(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        self._store_patch = patch.object(approvals_store, "APPROVALS_STORE_PATH", self.store_path)
        self._store_patch.start()
        assert TestClient is not None
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._store_patch.stop()
        os.unlink(self.store_path)

    def test_path_mismatch_403(self) -> None:
        rec = create_pending(
            "rid",
            "filesystem.path.read_external",
            "P1",
            {"path": "/allowed/file.txt"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        resp = self.client.post(
            "/actions/read-external-file",
            json={"approval_id": rec["approval_id"], "path": "/other/file.txt"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_success_delegates_to_system_agent(self) -> None:
        rec = create_pending(
            "rid",
            "filesystem.path.read_external",
            "P1",
            {"path": "/allowed/file.txt"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_read_external_file") as mock_call:
            mock_call.return_value = {"request_id": "r1", "content": "ok", "path": "/allowed/file.txt"}
            resp = self.client.post(
                "/actions/read-external-file",
                json={"approval_id": rec["approval_id"], "path": "/allowed/file.txt"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("content"), "ok")
        mock_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
