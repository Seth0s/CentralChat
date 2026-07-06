"""ADR-016 — modality_models resolver."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modality_models import (
    ROLE_SOCIAL_COPY,
    ROLE_SUMMARY,
    ROLE_VISION_PERCEIVE,
    ROLE_WEB_RESEARCH_DEFAULT,
    build_modality_invocation_entry,
    canonical_modality_role,
    clear_modality_models_cache,
    load_modality_models_map,
    modality_composer_label,
    modality_models_public_snapshot,
    record_modality_invocation_from_tool_result,
    resolve_modality_call_params,
    resolve_modality_model_id,
)


class TestModalityModels(unittest.TestCase):
    def tearDown(self) -> None:
        clear_modality_models_cache()

    def test_canonical_role_alias_web_research(self) -> None:
        self.assertEqual(canonical_modality_role("web_research"), ROLE_WEB_RESEARCH_DEFAULT)

    def test_unknown_role_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_modality_model_id("brain")
        self.assertIn("modality_role_desconhecido", str(ctx.exception))

    def test_json_development_summary(self) -> None:
        payload = {
            "schema_version": 1,
            "development": {ROLE_SUMMARY: "deepseek/deepseek-v4-flash:free"},
            "production": {ROLE_SUMMARY: "google/gemini-2.5-flash-lite"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            path = f.name
        try:
            with patch("app.modality_models.MODALITY_MODELS_PATH", path):
                with patch("app.config.CENTRAL_APP_ENV", "development"):
                    with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", ""):
                        clear_modality_models_cache()
                        mid = resolve_modality_model_id("summary")
                        self.assertEqual(mid, "deepseek/deepseek-v4-flash:free")
        finally:
            Path(path).unlink(missing_ok=True)
            clear_modality_models_cache()

    def test_env_override_wins_over_json(self) -> None:
        payload = {
            "development": {ROLE_SUMMARY: "google/gemma-4-26b-a4b-it:free"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            path = f.name
        try:
            with patch("app.modality_models.MODALITY_MODELS_PATH", path):
                with patch("app.config.CENTRAL_APP_ENV", "development"):
                    with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", "vendor/env-model"):
                        clear_modality_models_cache()
                        self.assertEqual(resolve_modality_model_id("summary"), "vendor/env-model")
        finally:
            Path(path).unlink(missing_ok=True)
            clear_modality_models_cache()

    def test_builtin_default_when_no_file(self) -> None:
        with patch("app.modality_models.MODALITY_MODELS_PATH", ""):
            with patch("app.config.CENTRAL_APP_ENV", "development"):
                with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", ""):
                    clear_modality_models_cache()
                    mid = resolve_modality_model_id("summary")
                    self.assertEqual(mid, "google/gemma-4-26b-a4b-it:free")

    def test_cache_reload_on_file_change(self) -> None:
        payload_v1 = {"development": {ROLE_SUMMARY: "vendor/model-a"}}
        payload_v2 = {"development": {ROLE_SUMMARY: "vendor/model-b"}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload_v1, f)
            path = f.name
        try:
            with patch("app.modality_models.MODALITY_MODELS_PATH", path):
                with patch("app.config.CENTRAL_APP_ENV", "development"):
                    with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", ""):
                        clear_modality_models_cache()
                        self.assertEqual(resolve_modality_model_id("summary"), "vendor/model-a")
                        Path(path).write_text(json.dumps(payload_v2), encoding="utf-8")
                        time.sleep(0.02)
                        clear_modality_models_cache()
                        mtime_map, _ = load_modality_models_map(force_reload=True)
                        self.assertEqual(mtime_map.get(ROLE_SUMMARY), "vendor/model-b")
                        self.assertEqual(resolve_modality_model_id("summary"), "vendor/model-b")
        finally:
            Path(path).unlink(missing_ok=True)
            clear_modality_models_cache()

    def test_resolve_call_params_uses_aux_profile(self) -> None:
        with patch("app.modality_models.MODALITY_MODELS_PATH", ""):
            with patch("app.config.CENTRAL_APP_ENV", "development"):
                with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", ""):
                    with patch("app.config.AUX_CLOUD_ROUTER_PROFILE", "cloud_gemini"):
                        clear_modality_models_cache()
                        profile, model_id = resolve_modality_call_params("summary")
                        self.assertEqual(profile, "cloud_gemini")
                        self.assertTrue(model_id)

    def test_public_snapshot_lists_roles(self) -> None:
        with patch("app.modality_models.MODALITY_MODELS_PATH", ""):
            with patch("app.config.CENTRAL_APP_ENV", "development"):
                with patch("app.config.CENTRAL_SUMMARY_MODEL_ID", ""):
                    clear_modality_models_cache()
                    snap = modality_models_public_snapshot()
                    self.assertEqual(snap["environment"], "development")
                    roles = {r["role"] for r in snap["roles"]}
                    self.assertIn(ROLE_SUMMARY, roles)
                    summary_row = next(r for r in snap["roles"] if r["role"] == ROLE_SUMMARY)
                    self.assertEqual(summary_row["source"], "default")
                    self.assertIn("label_pt", summary_row)

    def test_composer_label_perception(self) -> None:
        self.assertEqual(modality_composer_label(ROLE_VISION_PERCEIVE), "Percepção")

    def test_modality_invocation_entry_shape(self) -> None:
        row = build_modality_invocation_entry(
            modality_role=ROLE_SOCIAL_COPY,
            model_id="x-ai/grok-4.1-fast",
            phase="tool:draft_social_post",
        )
        self.assertEqual(row["modality_role"], ROLE_SOCIAL_COPY)
        self.assertEqual(row["label_pt"], "Copy")
        self.assertEqual(row["phase"], "tool:draft_social_post")

    def test_record_invocation_from_tool_result(self) -> None:
        inv: list[dict[str, str]] = []
        record_modality_invocation_from_tool_result(
            inv,
            tool_name="web_research",
            result={
                "modality_role": ROLE_WEB_RESEARCH_DEFAULT,
                "model_id": "perplexity/sonar-pro",
            },
        )
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["modality_role"], ROLE_WEB_RESEARCH_DEFAULT)


if __name__ == "__main__":
    unittest.main()
