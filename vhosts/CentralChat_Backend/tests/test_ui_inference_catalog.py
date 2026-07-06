"""GET /ui/inference_catalog — merge allowlist com lista do fornecedor (v2)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.server import app


def _minimal_snap(**overrides: object) -> dict:
    base = {
        "inference_destination": "local",
        "llm_model_id": "",
        "effective_router_profile": "eco",
        "active_model_override": None,
        "inference_resolve_error": None,
        "api_router_profile": "cloud_openai",
        "cloud_models": [],
        "model_router_configured": True,
        "allow_model_override_for_api_profile": True,
    }
    base.update(overrides)
    return base


class TestUiInferenceCatalog(unittest.TestCase):
    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap())
    @patch(
        "app.server.load_cloud_models_catalog",
        return_value=[
            {"id": "gpt-4o-mini", "label": "Mini"},
            {"id": "gpt-secret", "label": "X"},
        ],
    )
    @patch(
        "app.server.get_vendor_catalog_cached",
        return_value=(
            [
                {"id": "gpt-4o-mini", "label": "Mini"},
                {"id": "gpt-4o", "label": "GPT-4o"},
            ],
            None,
        ),
    )
    @patch("app.server.get_model_router_public_config", return_value={"profiles": ["cloud_openai"]})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_dynamic_intersect(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("cloud_models_source"), "dynamic_intersect")
        resolved = body.get("cloud_models_resolved") or []
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["id"], "gpt-4o-mini")

    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap(model_router_configured=False))
    @patch(
        "app.server.load_cloud_models_catalog",
        return_value=[{"id": "gpt-4o-mini", "label": "Mini"}],
    )
    @patch("app.server.get_model_router_public_config", return_value={})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_static_when_router_not_configured(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("cloud_models_source"), "static")
        self.assertIsNone(body.get("cloud_models_vendor_note"))

    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap())
    @patch("app.server.load_cloud_models_catalog", return_value=[])
    @patch(
        "app.server.get_vendor_catalog_cached",
        return_value=([{"id": "z1", "label": "z1"}, {"id": "a2", "label": "a2"}], None),
    )
    @patch("app.server.get_model_router_public_config", return_value={})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_dynamic_open_without_allowlist_file(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("cloud_models_source"), "dynamic_open")
        resolved = body.get("cloud_models_resolved") or []
        self.assertEqual([x["id"] for x in resolved], ["a2", "z1"])
        page = body.get("cloud_models_vendor_page") or []
        self.assertEqual(len(page), 2)
        self.assertEqual(body.get("cloud_models_vendor_total"), 2)
        self.assertEqual(body.get("vendor_page"), 1)
        self.assertEqual(body.get("vendor_page_size"), 50)

    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap())
    @patch(
        "app.server.load_cloud_models_catalog",
        return_value=[],
    )
    @patch(
        "app.server.get_vendor_catalog_cached",
        return_value=(
            [{"id": f"m{i}", "label": f"L{i}"} for i in range(5)],
            None,
        ),
    )
    @patch("app.server.get_model_router_public_config", return_value={})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_vendor_page_second_slice(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog?vendor_page=2&vendor_page_size=2")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("cloud_models_vendor_total"), 5)
        page = body.get("cloud_models_vendor_page") or []
        self.assertEqual(len(page), 2)
        self.assertEqual(page[0]["id"], "m2")
        self.assertEqual(page[1]["id"], "m3")
        self.assertTrue(body.get("cloud_models_allowlist_edit_enabled") in (True, False))

    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap())
    @patch("app.server.load_cloud_models_catalog", return_value=[])
    @patch(
        "app.server.get_vendor_catalog_cached",
        return_value=(
            [
                {"id": "a0", "label": "A0"},
                {"id": "a1", "label": "A1"},
                {"id": "b0", "label": "B0"},
                {"id": "z0", "label": "L0"},
                {"id": "z1", "label": "L1"},
            ],
            None,
        ),
    )
    @patch("app.server.get_model_router_public_config", return_value={})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_vendor_q_filters_before_pagination(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog?vendor_q=0&vendor_page_size=2&vendor_page=1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("vendor_q"), "0")
        self.assertEqual(body.get("cloud_models_vendor_total_all"), 5)
        self.assertEqual(body.get("cloud_models_vendor_total"), 3)
        page = body.get("cloud_models_vendor_page") or []
        self.assertEqual([x["id"] for x in page], ["a0", "b0"])

    @patch("app.server._ui_inference_snapshot", return_value=_minimal_snap())
    @patch("app.server.load_cloud_models_catalog", return_value=[])
    @patch(
        "app.server.get_vendor_catalog_cached",
        return_value=(
            [
                {"id": "a0", "label": "A0"},
                {"id": "a1", "label": "A1"},
                {"id": "b0", "label": "B0"},
                {"id": "z0", "label": "L0"},
                {"id": "z1", "label": "L1"},
            ],
            None,
        ),
    )
    @patch("app.server.get_model_router_public_config", return_value={})
    @patch("app.server.load_inference_routing", return_value=None)
    def test_vendor_q_second_page(self, *_mocks: MagicMock) -> None:
        client = TestClient(app)
        r = client.get("/ui/inference_catalog?vendor_q=0&vendor_page_size=2&vendor_page=2")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        page = body.get("cloud_models_vendor_page") or []
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0]["id"], "z0")


if __name__ == "__main__":
    unittest.main()
