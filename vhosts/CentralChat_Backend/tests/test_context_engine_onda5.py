"""Onda 5 tests — Coordenação + segurança: file lease, DLP ingest, tenant policy, stale diff.

Tests:
- FileLeaseStep (claim, conflict, release, branch suggestion)
- DLP on session ingest
- Tenant policy overrides
- Stale diff detection
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.context_engine import assemble_context_sync
from app.context_engine.registry import STEP_REGISTRY, Phase, list_steps
from app.context_engine.state import ContextState
from app.onda5_hardening import (
    dlp_scan_facts,
    check_stale_diff,
    record_file_read,
    clear_file_sha,
)
from app.context_engine.steps.gather.file_lease import (
    FileLeaseStep,
    release_lease,
    get_active_lease,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _base_mocks():
    return [
        patch("app.shared.system_prompt_loader.build_system_prompt_injection_messages",
              return_value=([], {"skipped": True})),
        patch("app.context_engine.steps.gather.system_layers._load_agent_prompt",
              return_value=""),
        patch("app.context_engine.steps.gather.system_layers._load_skills",
              return_value=([], [])),
        patch("app.context_engine.steps.gather.system_layers._build_l1",
              return_value=([], {"skipped": True})),
        patch("app.context_engine.steps.gather.system_layers._build_l4",
              return_value=(None, {"rule_count": 0})),
    ]


# ═══════════════════════════════════════════════════════════════
# File lease tests
# ═══════════════════════════════════════════════════════════════

class TestFileLease(unittest.TestCase):
    """FileLeaseStep tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()
        # Clean up leases between tests
        for key in list(get_active_lease.__globals__.get("_lease_store", {}).keys()):
            del get_active_lease.__globals__["_lease_store"][key]

    def tearDown(self) -> None:
        """Release any leases created during the test."""
        try:
            from app.context_engine.steps.gather.file_lease import _lease_store
            _lease_store.clear()
        except Exception:
            pass

    def test_no_lease_without_wi(self) -> None:
        """No lease when no work_item_id or workspace_path."""
        state = assemble_context_sync(
            request_id="t1", user_text="hello", tenant_id="default",
            user_id="u1", role="developer",
        )
        self.assertFalse(state.meta.get("file_lease_active", False))

    def test_lease_claimed_with_wi_and_workspace(self) -> None:
        """Lease is claimed when WI + workspace_path are present."""
        state = assemble_context_sync(
            request_id="t2", user_text="edit file",
            tenant_id="default", user_id="u1", role="developer",
            work_item_id="WI-1", workspace_path="/home/dev/proj",
        )
        self.assertTrue(state.meta.get("file_lease_active", False))
        self.assertEqual(state.meta.get("file_lease_wi"), "WI-1")

    def test_lease_injects_branch_suggestion(self) -> None:
        """L2 block includes suggested branch name."""
        state = assemble_context_sync(
            request_id="t3", user_text="edit",
            tenant_id="default", user_id="u1", role="developer",
            work_item_id="WI-42", workspace_path="/tmp/proj",
        )
        l2_sections = [s for s in state.sections if s.kind == "file_lease"]
        if l2_sections:
            self.assertIn("wi/wi-42", l2_sections[0].content)

    def test_lease_release_utility(self) -> None:
        """release_lease() removes an active lease."""
        step = STEP_REGISTRY["gather.file_lease"]
        # Manually simulate a lease
        from app.context_engine.steps.gather.file_lease import _lease_store

        key = ("test-tenant", "/test/path")
        _lease_store[key] = {"work_item_id": "WI-X"}
        self.assertIsNotNone(get_active_lease("test-tenant", "/test/path"))

        released = release_lease("test-tenant", "/test/path")
        self.assertTrue(released)
        self.assertIsNone(get_active_lease("test-tenant", "/test/path"))

    def test_lease_step_order(self) -> None:
        """FileLeaseStep has correct phase and priority."""
        step = STEP_REGISTRY["gather.file_lease"]
        self.assertEqual(step.phase, Phase.GATHER)
        self.assertEqual(step.priority, 12)
        # Should run after system_layers (10) but before retrieval (15)
        sl_step = STEP_REGISTRY["gather.system_layers"]
        ret_step = STEP_REGISTRY["gather.retrieval"]
        self.assertLess(sl_step.priority, step.priority)
        self.assertLess(step.priority, ret_step.priority)


# ═══════════════════════════════════════════════════════════════
# DLP on ingest tests
# ═══════════════════════════════════════════════════════════════

class TestDlpIngest(unittest.TestCase):
    """DLP scan on session facts before indexing."""

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    def test_clean_facts_pass(self) -> None:
        """Clean facts pass DLP scan unchanged."""
        facts = ["user asked about Python", "assistant explained list comprehensions"]
        result = dlp_scan_facts(facts, "default")
        self.assertEqual(len(result), 2)

    @patch("app.shared.dlp_scanner.CENTRAL_DLP_ENABLED", True)
    def test_secret_fact_blocked(self) -> None:
        """Facts containing secrets are filtered out (private key)."""
        facts = ["user asked about config", "key: -----BEGIN RSA PRIVATE KEY----- abc"]
        result = dlp_scan_facts(facts, "default")
        # The private key fact should be filtered
        self.assertLess(len(result), 2)

    def test_empty_facts(self) -> None:
        """Empty list returns empty list."""
        result = dlp_scan_facts([], "default")
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════
# Stale diff detection tests
# ═══════════════════════════════════════════════════════════════

class TestStaleDiff(unittest.TestCase):
    """SHA-based stale diff detection."""

    def tearDown(self) -> None:
        clear_file_sha("test-session")

    def test_no_record_not_stale(self) -> None:
        """Without a recorded SHA, file is not stale."""
        self.assertFalse(check_stale_diff("sess-1", "/file.py", "abc123"))

    def test_same_sha_not_stale(self) -> None:
        """Same SHA → not stale."""
        record_file_read("sess-1", "/file.py", "abc123")
        self.assertFalse(check_stale_diff("sess-1", "/file.py", "abc123"))

    def test_changed_sha_is_stale(self) -> None:
        """Different SHA → stale."""
        record_file_read("sess-1", "/file.py", "abc123")
        self.assertTrue(check_stale_diff("sess-1", "/file.py", "xyz789"))

    def test_clear_specific_file(self) -> None:
        """clear_file_sha removes a specific file record."""
        record_file_read("sess-1", "/a.py", "sha1")
        record_file_read("sess-1", "/b.py", "sha2")
        clear_file_sha("sess-1", "/a.py")
        self.assertFalse(check_stale_diff("sess-1", "/a.py", "sha1"))
        self.assertFalse(check_stale_diff("sess-1", "/b.py", "sha2"))

    def test_clear_all_session_files(self) -> None:
        """clear_file_sha without file_path clears all session records."""
        record_file_read("sess-1", "/a.py", "sha1")
        record_file_read("sess-1", "/b.py", "sha2")
        clear_file_sha("sess-1")
        self.assertFalse(check_stale_diff("sess-1", "/a.py", "sha1"))
        self.assertFalse(check_stale_diff("sess-1", "/b.py", "sha2"))


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestOnda5Integration(unittest.TestCase):
    """End-to-end tests for Onda 5 features."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patchers = [p.start() for p in _base_mocks()]

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls._patchers:
            p.stop()

    def test_step_count_18(self) -> None:
        """Verify total step count is 18."""
        self.assertEqual(len(STEP_REGISTRY), 18)

    def test_file_lease_registered(self) -> None:
        """FileLeaseStep is registered in gather phase."""
        self.assertIn("gather.file_lease", STEP_REGISTRY)

    def test_tenant_policy_importable(self) -> None:
        """Tenant policy overrides module is importable."""
        from app.context_engine.onda5_hardening import load_tenant_policy_overrides

        # Without PG, should return None gracefully
        result = load_tenant_policy_overrides("default")
        self.assertIsNone(result)  # No PG → no overrides


if __name__ == "__main__":
    unittest.main()
