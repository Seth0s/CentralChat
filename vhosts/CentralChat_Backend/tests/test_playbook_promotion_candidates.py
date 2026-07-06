"""NEXT #7 — candidatos a promoção governada (audit hook + materializar + descartar)."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app import approvals_store as ast
from app import playbook_promotion_candidates as ppc
from app import playbook_store as ps
from app.approvals_store import create_pending
from app.orchestrator_audit import write_event


class TestPlaybookPromotionCandidates(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.promo_path = self.root / "promo.json"
        self.playbook_path = self.root / "playbook.json"
        self.approvals_path = self.root / "approvals.json"
        self.audit_path = self.root / "audit.jsonl"

    def tearDown(self) -> None:
        self._td.cleanup()

    def _enter_patches(self, stack: ExitStack) -> None:
        stack.enter_context(patch.object(ppc, "PLAYBOOK_PROMOTION_CANDIDATES_PATH", str(self.promo_path)))
        stack.enter_context(patch.object(ppc, "PLAYBOOK_FEATURE_ENABLED", True))
        stack.enter_context(patch.object(ppc, "PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED", True))
        stack.enter_context(patch.object(ps, "PLAYBOOK_STORE_PATH", str(self.playbook_path)))
        stack.enter_context(patch.object(ps, "PLAYBOOK_FEATURE_ENABLED", True))
        stack.enter_context(patch.object(ast, "APPROVALS_STORE_PATH", str(self.approvals_path)))
        stack.enter_context(patch("app.orchestrator_audit.ORCHESTRATOR_AUDIT_LOG_PATH", str(self.audit_path)))

    def test_write_event_creates_candidate_and_dedupes(self) -> None:
        with ExitStack() as stack:
            self._enter_patches(stack)
            rec = create_pending(
                request_id="rid-promo-12345678",
                action_id="systemd.unit.restart",
                risk_level="P2",
                payload={"unit": "central-orchestrator.service"},
            tenant_id="default",
                requires_double_confirmation=False,
            )
            aid = str(rec["approval_id"])
            ev = {
                "event": "p2_systemd_restart_done",
                "approval_id": aid,
                "request_id": "rid-promo-12345678",
                "action_id": "systemd.unit.restart",
                "unit": "central-orchestrator.service",
                "result_ok": True,
            }
            write_event(dict(ev))
            items = ppc.list_pending_candidates()
            self.assertEqual(len(items), 1, items)
            self.assertEqual(items[0]["approval_id"], aid)
            write_event(dict(ev))
            items2 = ppc.list_pending_candidates()
            self.assertEqual(len(items2), 1)

    def test_materialize_creates_playbook_entry(self) -> None:
        with ExitStack() as stack:
            self._enter_patches(stack)
            rec = create_pending(
                request_id="rid-promo-87654321",
                action_id="process.signal",
                risk_level="P1",
                payload={"pid": 42},
            tenant_id="default",
            )
            aid = str(rec["approval_id"])
            write_event(
                {
                    "event": "p1_process_signal_done",
                    "approval_id": aid,
                    "request_id": "rid-promo-87654321",
                    "action_id": "process.signal",
                    "pid": 42,
                    "result_ok": True,
                }
            )
            items = ppc.list_pending_candidates()
            cid = items[0]["candidate_id"]
            out = ppc.materialize_candidate(cid, title_override="Título curado", body_override=None)
            self.assertIsNotNone(out)
            assert out is not None
            self.assertEqual(out["playbook_entry"]["title"], "Título curado")
            meta = ps.list_playbook_entries_meta()
            self.assertEqual(len(meta), 1)
            self.assertEqual(meta[0]["title"], "Título curado")
            self.assertEqual(len(ppc.list_pending_candidates()), 0)

    def test_dismiss(self) -> None:
        with ExitStack() as stack:
            self._enter_patches(stack)
            rec = create_pending(
                request_id="rid-dismiss-12345678",
                action_id="systemd.unit.stop",
                risk_level="P2",
                payload={"unit": "foo.service"},
            tenant_id="default",
            )
            aid = str(rec["approval_id"])
            write_event(
                {
                    "event": "p2_systemd_stop_done",
                    "approval_id": aid,
                    "request_id": "rid-dismiss-12345678",
                    "action_id": "systemd.unit.stop",
                    "unit": "foo.service",
                    "result_ok": True,
                }
            )
            items = ppc.list_pending_candidates()
            cid = items[0]["candidate_id"]
            row = ppc.dismiss_candidate(cid)
            self.assertIsNotNone(row)
            self.assertEqual(len(ppc.list_pending_candidates()), 0)
            data = json.loads(self.promo_path.read_text(encoding="utf-8"))
            dismissed = [x for x in data["items"] if x.get("candidate_id") == cid]
            self.assertEqual(dismissed[0].get("status"), "dismissed")


if __name__ == "__main__":
    unittest.main()
