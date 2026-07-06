"""Tests for secret_refs_store (Phase 2 metadata helpers)."""

from __future__ import annotations

import unittest

from app.shared.secret_refs_store import secret_fingerprint, secret_prefix


class SecretRefsStoreTest(unittest.TestCase):
    def test_fingerprint_stable(self) -> None:
        self.assertEqual(secret_fingerprint("sk-test"), secret_fingerprint("sk-test"))
        self.assertNotEqual(secret_fingerprint("sk-a"), secret_fingerprint("sk-b"))

    def test_prefix_masks_value(self) -> None:
        self.assertEqual(secret_prefix("sk-ant-test"), "sk-a…")
        self.assertEqual(secret_prefix("ab"), "****")


if __name__ == "__main__":
    unittest.main()
