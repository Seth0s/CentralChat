"""Pré-Fase 11 — system_prompt_manifest."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app import system_prompt_manifest as spm


class TestSystemPromptManifest(unittest.TestCase):
    def tearDown(self) -> None:
        spm.reset_system_prompt_cache_for_tests()

    def test_effective_origin_overlay_wins(self) -> None:
        overlay_p = self._temp_overlay()
        with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_RELOAD_MODE", "mtime_poll"):
            with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES", 262144):
                with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION", 1):
                    with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_ID", "test-id"):
                        with patch.object(
                            spm._cfg,
                            "CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH",
                            str(Path(__file__).resolve().parent.parent / "bundled" / "system_prompt.default.md"),
                        ):
                            with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH", overlay_p):
                                snap = spm.get_system_prompt_public_snapshot()
        self.assertEqual(snap["effective_origin"], "central_root_overlay")
        self.assertTrue(snap["overlay_present"])
        self.assertEqual(snap["composition_order"][0], "l6_policy")

    def _temp_overlay(self) -> str:
        from tempfile import NamedTemporaryFile

        f = NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        try:
            f.write("# overlay test\nhello\n")
            path = f.name
        finally:
            f.close()
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        return path

    def test_startup_only_freezes(self) -> None:
        with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_RELOAD_MODE", "startup_only"):
            with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES", 262144):
                with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION", 1):
                    with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_BUNDLED_ID", "x"):
                        with patch.object(
                            spm._cfg,
                            "CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH",
                            str(Path(__file__).resolve().parent.parent / "bundled" / "system_prompt.default.md"),
                        ):
                            with patch.object(spm._cfg, "CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH", ""):
                                a = spm.get_system_prompt_public_snapshot()
                                b = spm.get_system_prompt_public_snapshot()
        self.assertEqual(a["bundled_content_sha256_16"], b["bundled_content_sha256_16"])


if __name__ == "__main__":
    unittest.main()
