"""P2-6: POST /actions/mutate-external-path valida approval + payload."""
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
except ImportError:  # pragma: no cover
    pass


@unittest.skipUnless(app is not None, "FastAPI app + deps em falta")
class TestMutateExternalAction(unittest.TestCase):
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

    def test_src_mismatch_403(self) -> None:
        rec = create_pending(
            "rid",
            "filesystem.path.mutate_external",
            "P2",
            {"operation": "delete", "src_path": "/allowed/a.txt"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        resp = self.client.post(
            "/actions/mutate-external-path",
            json={
                "approval_id": rec["approval_id"],
                "operation": "delete",
                "src_path": "/other/a.txt",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_delegates(self) -> None:
        rec = create_pending(
            "rid",
            "filesystem.path.mutate_external",
            "P2",
            {"operation": "delete", "src_path": "/allowed/a.txt"},
            tenant_id="default",
            requires_double_confirmation=False,
        )
        approve_or_first_double_step(rec["approval_id"], tenant_id="default")
        with patch("app.server.call_system_agent_mutate_external_path") as mock_call:
            mock_call.return_value = {"request_id": "r1", "result": "deleted", "error": None}
            resp = self.client.post(
                "/actions/mutate-external-path",
                json={
                    "approval_id": rec["approval_id"],
                    "operation": "delete",
                    "src_path": "/allowed/a.txt",
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("result"), "deleted")
        mock_call.assert_called_once()
        kw = mock_call.call_args.kwargs
        self.assertIsNone(kw.get("dst_path"))


if __name__ == "__main__":
    unittest.main()
