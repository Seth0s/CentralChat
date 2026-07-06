"""Resolução local vs API + allowlist."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.inference_resolve import resolve_aux_llm_call_params, resolve_llm_call_params


class TestInferenceResolve(unittest.TestCase):
    def test_local_picks_legacy_eco(self) -> None:
        router = {"profiles": ["eco", "balanced", "quality"], "default_profile": "balanced"}
        prefs: dict = {"inference_destination": "local"}
        p, mo = resolve_llm_call_params(
            active_ui_profile="A",
            prefs=prefs,
            router_public=router,
        )
        self.assertIsNone(mo)
        self.assertEqual(p, "eco")

    def test_local_prefers_local_prefixed_when_present(self) -> None:
        router = {
            "profiles": ["local_eco", "local_balanced", "cloud_openai"],
            "default_profile": "local_balanced",
        }
        prefs = {"inference_destination": "local"}
        p, mo = resolve_llm_call_params(
            active_ui_profile="B",
            prefs=prefs,
            router_public=router,
        )
        self.assertIsNone(mo)
        self.assertEqual(p, "local_balanced")

    def test_api_requires_router_url(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": ""}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", ""):
            with self.assertRaises(ValueError) as ctx:
                resolve_llm_call_params(
                    active_ui_profile="B",
                    prefs=prefs,
                    router_public=router,
                )
            self.assertIn("MODEL_ROUTER_URL", str(ctx.exception))

    def test_api_with_allowlist_enforcement(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": "gpt-secret"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.load_cloud_models_catalog",
                return_value=[{"id": "gpt-4o-mini", "label": "Mini"}],
            ):
                with self.assertRaises(ValueError) as ctx:
                    resolve_llm_call_params(
                        active_ui_profile="B",
                        prefs=prefs,
                        router_public=router,
                    )
                self.assertIn("allowlist", str(ctx.exception))

    def test_api_rejects_sonar_not_on_ui_allowlist(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": "perplexity/sonar-pro"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.load_cloud_models_catalog",
                return_value=[
                    {"id": "deepseek/deepseek-v4-flash:free", "enabled": True},
                    {"id": "google/gemma-4-26b-a4b-it:free", "enabled": True},
                ],
            ):
                with self.assertRaises(ValueError) as ctx:
                    resolve_llm_call_params(
                        active_ui_profile="B",
                        prefs=prefs,
                        router_public=router,
                    )
                self.assertIn("allowlist", str(ctx.exception))

    def test_api_allowlisted_model(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": "gpt-4o-mini"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.load_cloud_models_catalog",
                return_value=[{"id": "gpt-4o-mini", "label": "Mini"}],
            ):
                p, mo = resolve_llm_call_params(
                    active_ui_profile="B",
                    prefs=prefs,
                    router_public=router,
                )
                self.assertEqual(p, "cloud_openai")
                self.assertEqual(mo, "gpt-4o-mini")

    def test_aux_local_prefers_local_eco(self) -> None:
        router = {"profiles": ["local_eco", "eco", "balanced"], "default_profile": "balanced"}
        prefs: dict = {"aux_llm_destination": "local"}
        p, mo = resolve_aux_llm_call_params(prefs=prefs, router_public=router)
        self.assertIsNone(mo)
        self.assertEqual(p, "local_eco")

    def test_aux_api_requires_router_url(self) -> None:
        router = {"profiles": ["cloud_gemini"], "default_profile": "balanced"}
        prefs = {"aux_llm_destination": "api", "aux_llm_model_id": ""}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", ""):
            with self.assertRaises(ValueError) as ctx:
                resolve_aux_llm_call_params(prefs=prefs, router_public=router)
            self.assertIn("MODEL_ROUTER_URL", str(ctx.exception))

    def test_aux_api_uses_modality_summary(self) -> None:
        router = {"profiles": ["cloud_gemini"], "default_profile": "balanced"}
        prefs = {"aux_llm_destination": "api"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.resolve_modality_call_params",
                return_value=("cloud_gemini", "google/gemini-2.5-flash-lite"),
            ):
                p, mo = resolve_aux_llm_call_params(prefs=prefs, router_public=router)
                self.assertEqual(p, "cloud_gemini")
                self.assertEqual(mo, "google/gemini-2.5-flash-lite")

    def test_api_auto_tier_picks_from_allowlist(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": "", "auto_tier": "economy"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.load_cloud_models_catalog",
                return_value=[
                    {"id": "z-big", "label": "Z", "enabled": True},
                    {"id": "a-small", "label": "A", "enabled": True},
                ],
            ):
                p, mo = resolve_llm_call_params(
                    active_ui_profile="B",
                    prefs=prefs,
                    router_public=router,
                )
        self.assertEqual(p, "cloud_openai")
        self.assertEqual(mo, "a-small")

    def test_api_auto_tier_premium_picks_last(self) -> None:
        router = {"profiles": ["cloud_openai"], "default_profile": "cloud_openai"}
        prefs = {"inference_destination": "api", "llm_model_id": "", "auto_tier": "premium"}
        with patch("app.inference_resolve.MODEL_ROUTER_URL", "http://mr:8005"):
            with patch(
                "app.inference_resolve.load_cloud_models_catalog",
                return_value=[
                    {"id": "m1", "enabled": True},
                    {"id": "m2", "enabled": True},
                    {"id": "m3", "enabled": True},
                ],
            ):
                _p, mo = resolve_llm_call_params(
                    active_ui_profile="B",
                    prefs=prefs,
                    router_public=router,
                )
        self.assertEqual(mo, "m3")


if __name__ == "__main__":
    unittest.main()
