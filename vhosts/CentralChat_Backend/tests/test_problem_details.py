"""RFC 9457 Problem Details on HTTP errors (Fase 2)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.server import app


class TestProblemDetails(unittest.TestCase):
    def test_validation_error_returns_problem_json(self) -> None:
        client = TestClient(app)
        r = client.post("/ui/preferences", json={"inference_destination": 12345})
        self.assertEqual(r.status_code, 422)
        self.assertIn("application/problem+json", r.headers.get("content-type", ""))
        body = r.json()
        self.assertEqual(body.get("status"), 422)
        self.assertIn("type", body)
        self.assertIn("detail", body)
        self.assertIsInstance(body.get("errors"), list)

    def test_http_error_returns_problem_json(self) -> None:
        client = TestClient(app)
        r = client.post("/ui/profile", json={"profile": "Z"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("application/problem+json", r.headers.get("content-type", ""))
        body = r.json()
        self.assertEqual(body.get("status"), 400)
        self.assertIn("detail", body)

    def test_config_includes_widget_feature_flags(self) -> None:
        client = TestClient(app)
        r = client.get("/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        w = body.get("widget_feature_flags")
        self.assertIsInstance(w, dict)
        self.assertIn("auto_tier_enabled", w)
        self.assertIn("multi_slot_graph_enabled", w)
        self.assertIn("composer_segments_in_stream", w)

    def test_config_includes_system_prompt(self) -> None:
        client = TestClient(app)
        r = client.get("/config")
        self.assertEqual(r.status_code, 200)
        sp = r.json().get("system_prompt")
        self.assertIsInstance(sp, dict)
        self.assertEqual(sp.get("schema_version"), 1)
        self.assertIn("composition_order", sp)
        self.assertIn("effective_origin", sp)

    def test_config_and_catalog_system_prompt_match(self) -> None:
        client = TestClient(app)
        c = client.get("/config").json().get("system_prompt")
        cat = client.get("/ui/inference_catalog").json().get("system_prompt")
        self.assertIsInstance(c, dict)
        self.assertEqual(c, cat)

    def test_config_and_catalog_widget_feature_flags_match(self) -> None:
        """Same snapshot for `widget_feature_flags` (Fase 2 / contrato §8.1)."""
        client = TestClient(app)
        c = client.get("/config").json().get("widget_feature_flags")
        cat = client.get("/ui/inference_catalog").json().get("widget_feature_flags")
        self.assertIsInstance(c, dict)
        self.assertEqual(c, cat)

    def test_config_and_catalog_auto_tier_policies_match(self) -> None:
        client = TestClient(app)
        c = client.get("/config").json().get("auto_tier_policies")
        cat = client.get("/ui/inference_catalog").json().get("auto_tier_policies")
        self.assertIsInstance(c, dict)
        self.assertEqual(c, cat)
        self.assertIn("tiers", c)
        self.assertEqual(set(c["tiers"].keys()), {"economy", "balanced", "premium"})

    def test_config_and_catalog_rate_limit_match(self) -> None:
        client = TestClient(app)
        c = client.get("/config").json().get("rate_limit")
        cat = client.get("/ui/inference_catalog").json().get("rate_limit")
        self.assertIsInstance(c, dict)
        self.assertEqual(c, cat)
        for k in ("enabled", "per_window", "window_seconds", "path_prefixes"):
            self.assertIn(k, c)

    def test_config_includes_modality_models(self) -> None:
        client = TestClient(app)
        mm = client.get("/config").json().get("modality_models")
        self.assertIsInstance(mm, dict)
        self.assertEqual(mm.get("schema_version"), 1)
        roles = mm.get("roles")
        self.assertIsInstance(roles, list)
        self.assertGreater(len(roles), 0)
        row = roles[0]
        for key in ("role", "model_id", "label_pt", "source"):
            self.assertIn(key, row)

    def test_config_and_catalog_modality_models_match(self) -> None:
        client = TestClient(app)
        c = client.get("/config").json().get("modality_models")
        cat = client.get("/ui/inference_catalog").json().get("modality_models")
        self.assertIsInstance(c, dict)
        self.assertEqual(c, cat)

    @patch("app.server.replace_widget_slot_graph", return_value=None)
    @patch(
        "app.server.load_widget_slot_graph",
        return_value={"version": 7, "edges": [{"slot_a": 1, "slot_b": 2}]},
    )
    @patch("app.server.WIDGET_MULTI_SLOT_ENABLED", True)
    def test_version_conflict_returns_problem_json(self, *_mocks: object) -> None:
        client = TestClient(app)
        r = client.patch(
            "/ui/widget_slot_graph",
            json={"version": 1, "edges": [{"slot_a": 1, "slot_b": 3}]},
        )
        self.assertEqual(r.status_code, 409)
        self.assertIn("application/problem+json", r.headers.get("content-type", ""))
        body = r.json()
        self.assertEqual(body.get("status"), 409)
        self.assertIn("current", body)


if __name__ == "__main__":
    unittest.main()
