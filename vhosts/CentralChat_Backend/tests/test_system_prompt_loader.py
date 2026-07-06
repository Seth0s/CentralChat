"""Fase 11 — system_prompt_loader."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import system_prompt_loader as spl


class TestSystemPromptLoader(unittest.TestCase):
    def test_bundled_only(self) -> None:
        with TemporaryDirectory() as td:
            bp = Path(td) / "b.md"
            bp.write_text("# Hi\nbody", encoding="utf-8")
            with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH", str(bp)):
                with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH", ""):
                    with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES", 50_000):
                        with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION", 2):
                            with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_ID", "tid"):
                                with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_ENABLED", False):
                                    with patch.object(spl._cfg, "CENTRAL_PRODUCT_PACK_ENABLED", False):
                                        msgs, audit = spl.build_system_prompt_injection_messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("[SYSTEM_BUNDLED", msgs[0]["content"])
        self.assertIn("body", msgs[0]["content"])
        self.assertTrue(audit["system_prompt_bundled_applied"])
        self.assertFalse(audit["system_prompt_l6_anchor_applied"])

    def test_l6_and_overlay(self) -> None:
        with TemporaryDirectory() as td:
            bp = Path(td) / "b.md"
            bp.write_text("x", encoding="utf-8")
            op = Path(td) / "o.md"
            op.write_text("overlay", encoding="utf-8")
            pol = Path(td) / "p.json"
            pol.write_text(json.dumps({"actions": {"a": {"allowed": True}}}), encoding="utf-8")
            with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH", str(bp)):
                with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH", str(op)):
                    with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES", 50_000):
                        with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION", 1):
                            with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_ID", "id"):
                                with patch.object(spl._cfg, "CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_ENABLED", True):
                                    with patch.object(spl._cfg, "CENTRAL_PRODUCT_PACK_ENABLED", False):
                                        with patch.object(spl._cfg, "SYSTEM_AGENT_POLICY_PATH", str(pol)):
                                            with patch.object(
                                                spl._cfg, "CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_MAX_CHARS", 2000
                                            ):
                                                msgs, audit = spl.build_system_prompt_injection_messages()
        self.assertEqual(len(msgs), 3)
        self.assertIn("[POLICY_ANCHOR]", msgs[0]["content"])
        self.assertIn("Action policy registry", msgs[0]["content"])
        self.assertTrue(audit["system_prompt_overlay_applied"])
        self.assertEqual(audit["system_prompt_overlay_chars"], len("overlay"))


if __name__ == "__main__":
    unittest.main()
