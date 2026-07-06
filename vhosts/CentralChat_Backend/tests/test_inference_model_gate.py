"""Gate L6 antes do model-router."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.inference_model_gate import (
    ADR16_DEV_UI_ALLOWLIST_SAMPLE,
    validate_modality_model_router_override,
    validate_outbound_model_router_override,
    validate_ui_model_router_override,
)


class TestInferenceModelGate(unittest.TestCase):
    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "")
    def test_noop_without_router(self) -> None:
        validate_outbound_model_router_override("anything")

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch(
        "app.inference_model_gate.load_cloud_models_catalog",
        return_value=[{"id": "ok-model", "enabled": True}],
    )
    def test_intersect_allowlisted(self, *_m: object) -> None:
        validate_outbound_model_router_override("ok-model")

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch("app.inference_model_gate.load_cloud_models_catalog", return_value=[{"id": "ok-model", "enabled": True}])
    def test_intersect_rejects(self, *_m: object) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            validate_outbound_model_router_override("evil")
        self.assertIn("allowlist", str(ctx.exception))

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "full_vendor")
    def test_full_vendor_shape(self) -> None:
        validate_outbound_model_router_override("google/gemini-2.0-flash-001")

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "full_vendor")
    def test_full_vendor_bad_shape(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            validate_outbound_model_router_override("no spaces allowed ")
        self.assertIn("formato", str(ctx.exception))

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch("app.inference_model_gate.load_cloud_models_catalog", return_value=[])
    def test_modality_mode_skips_ui_allowlist(self, *_m: object) -> None:
        validate_outbound_model_router_override(
            "perplexity/sonar-pro",
            allowlist_mode="modality",
        )

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    def test_modality_mode_rejects_bad_shape(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            validate_outbound_model_router_override(
                "bad id",
                allowlist_mode="modality",
            )
        self.assertIn("formato", str(ctx.exception))

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch(
        "app.inference_model_gate.load_cloud_models_catalog",
        return_value=[
            {"id": mid, "enabled": True} for mid in sorted(ADR16_DEV_UI_ALLOWLIST_SAMPLE)
        ],
    )
    def test_sonar_pro_rejected_in_ui_mode(self, *_m: object) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            validate_ui_model_router_override("perplexity/sonar-pro")
        self.assertIn("allowlist", str(ctx.exception))

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch(
        "app.inference_model_gate.load_cloud_models_catalog",
        return_value=[
            {"id": mid, "enabled": True} for mid in sorted(ADR16_DEV_UI_ALLOWLIST_SAMPLE)
        ],
    )
    def test_sonar_pro_allowed_in_modality_mode(self, *_m: object) -> None:
        validate_modality_model_router_override("perplexity/sonar-pro")

    @patch("app.inference_model_gate.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.inference_model_gate.CLOUD_UI_MODEL_CATALOG_MODE", "intersect")
    @patch(
        "app.inference_model_gate.load_cloud_models_catalog",
        return_value=[
            {"id": mid, "enabled": True} for mid in sorted(ADR16_DEV_UI_ALLOWLIST_SAMPLE)
        ],
    )
    def test_summary_model_allowed_in_modality_rejected_in_ui(self, *_m: object) -> None:
        summary_id = "google/gemini-2.5-flash-lite"
        validate_modality_model_router_override(summary_id)
        with self.assertRaises(RuntimeError):
            validate_ui_model_router_override(summary_id)


if __name__ == "__main__":
    unittest.main()
