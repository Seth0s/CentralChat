"""L2 — preferências locais (assistant_preferences.json)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import assistant_preferences as ap


class TestAssistantPreferences(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.path = Path(self._td.name) / "assistant_preferences.json"

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_load_defaults_without_file(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            d = ap.load_preferences()
        self.assertEqual(d["verbosity"], "normal")
        self.assertFalse(d["default_include_memory_recall"])
        self.assertEqual(d["aux_llm_destination"], "local")
        self.assertEqual(d["embedding_destination"], "local")

    def test_merge_and_roundtrip(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            out = ap.merge_preferences_patch(
                {
                    "verbosity": "short",
                    "default_include_memory_recall": True,
                    "tone_hint": "  calma  ",
                }
            )
            self.assertEqual(out["verbosity"], "short")
            self.assertTrue(out["default_include_memory_recall"])
            self.assertEqual(out["tone_hint"], "calma")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["verbosity"], "short")

    def test_preferences_system_messages_short(self) -> None:
        msgs = ap.preferences_system_messages({"verbosity": "short", "tone_hint": ""})
        self.assertEqual(len(msgs), 1)
        self.assertIn("curtas", msgs[0]["content"])

    def test_merge_default_include_playbook(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            out = ap.merge_preferences_patch({"default_include_playbook": True})
        self.assertTrue(out["default_include_playbook"])

    def test_merge_auto_tier_and_clear_on_manual(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            out = ap.merge_preferences_patch(
                {"inference_destination": "api", "llm_model_id": "", "auto_tier": "economy"}
            )
        self.assertEqual(out["auto_tier"], "economy")
        with patch.object(ap, "CLOUD_UI_MODEL_CATALOG_MODE", "intersect"):
            with patch(
                "app.assistant_preferences.load_cloud_models_catalog",
                return_value=[{"id": "gpt-4o-mini", "label": "Mini", "enabled": True}],
            ):
                with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
                    out2 = ap.merge_preferences_patch({"llm_model_id": "gpt-4o-mini"})
        self.assertEqual(out2["llm_model_id"], "gpt-4o-mini")
        self.assertEqual(out2["auto_tier"], "")

    def test_auto_tier_cleared_when_inference_local(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            ap.merge_preferences_patch(
                {"inference_destination": "api", "llm_model_id": "", "auto_tier": "premium"}
            )
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            out = ap.merge_preferences_patch({"inference_destination": "local"})
        self.assertEqual(out["auto_tier"], "")

    def test_invalid_verbosity_raises(self) -> None:
        with patch.object(ap, "ASSISTANT_PREFERENCES_STORE_PATH", str(self.path)):
            with self.assertRaises(ValueError):
                ap.merge_preferences_patch({"verbosity": "mega"})

    def test_resolved_assistant_payload(self) -> None:
        from app.server import AssistantTextRequest, _resolved_assistant_payload

        with patch("app.server.load_preferences") as m:
            m.return_value = {
                "verbosity": "normal",
                "tone_hint": "",
                "default_include_long_session_memory": True,
                "default_include_memory_recall": True,
                "default_include_host_context": True,
                "default_include_playbook": True,
                "default_include_capability_digest": True,
                "default_use_agent_tools": False,
            }
            p = AssistantTextRequest(text="x", use_saved_assistant_defaults=True)
            r = _resolved_assistant_payload(p)
        self.assertTrue(r.include_long_session_memory)
        self.assertTrue(r.include_memory_recall)
        self.assertTrue(r.include_host_context)
        self.assertTrue(r.include_playbook)
        self.assertTrue(r.include_capability_digest)


if __name__ == "__main__":
    unittest.main()
