"""ADR-016 — OpenRouter STT/TTS (mock HTTP)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.clients import call_stt, call_tts
from app.openrouter_audio import (
    openrouter_stt_configured,
    openrouter_tts_configured,
    resolve_openrouter_api_key,
    stack_health_stt_entry,
    stack_health_tts_entry,
    synthesize_speech_openrouter,
)


class TestOpenrouterAudio(unittest.TestCase):
    def test_resolve_key_from_env(self) -> None:
        with patch("app.openrouter_audio.OPENROUTER_API_KEY", "sk-test"):
            with patch("app.openrouter_audio.resolve_secret", return_value="sk-test"):
                self.assertEqual(resolve_openrouter_api_key(), "sk-test")

    @patch("app.openrouter_audio.DISABLE_TTS", False)
    @patch("app.openrouter_audio.resolve_openrouter_api_key", return_value="sk-test")
    @patch("app.openrouter_audio.resolve_modality_model_id", return_value="openai/tts-model")
    def test_tts_configured(self, *_m: object) -> None:
        self.assertTrue(openrouter_tts_configured())

    @patch("app.openrouter_audio.DISABLE_STT", False)
    @patch("app.openrouter_audio.MODEL_ROUTER_URL", "http://mr:8005")
    @patch("app.openrouter_audio.resolve_modality_model_id", return_value="google/gemini-2.5-flash-lite")
    def test_stt_configured_via_router(self, *_m: object) -> None:
        self.assertTrue(openrouter_stt_configured())

    @patch("app.openrouter_audio.httpx.Client")
    @patch("app.openrouter_audio.resolve_openrouter_api_key", return_value="sk-test")
    @patch("app.openrouter_audio.resolve_modality_model_id", return_value="openai/tts-model")
    @patch("app.openrouter_audio._audio_output_dir")
    def test_synthesize_writes_file(
        self,
        mock_dir: MagicMock,
        *_m: object,
    ) -> None:
        from pathlib import Path

        tmp = Path(self._testMethodName + "_audio")
        tmp.mkdir(exist_ok=True)
        mock_dir.return_value = tmp
        inst = MagicMock()
        resp = MagicMock()
        resp.content = b"\x00\x01mp3"
        resp.raise_for_status = MagicMock()
        inst.post.return_value = resp
        cm = MagicMock()
        cm.__enter__.return_value = inst
        cm.__exit__.return_value = False
        with patch("app.openrouter_audio.httpx.Client", return_value=cm):
            path = synthesize_speech_openrouter("ola", filename="out.mp3")
        self.assertTrue(path.endswith("out.mp3"))
        self.assertTrue(Path(path).is_file())
        Path(path).unlink(missing_ok=True)
        tmp.rmdir()

    @patch("app.clients.DISABLE_TTS", False)
    @patch("app.clients.openrouter_tts_configured", return_value=True)
    @patch("app.clients.synthesize_speech_openrouter", return_value="/tmp/fake.mp3")
    def test_call_tts_openrouter_path(self, *_m: object) -> None:
        self.assertEqual(call_tts("hello"), "/tmp/fake.mp3")

    @patch("app.clients.DISABLE_STT", False)
    @patch("app.clients.openrouter_stt_configured", return_value=True)
    @patch("app.clients.transcribe_audio_bytes", return_value="texto falado")
    def test_call_stt_openrouter_path(self, *_m: object) -> None:
        self.assertEqual(call_stt(b"\x00\x01", content_type="audio/wav"), "texto falado")

    @patch("app.openrouter_audio.DISABLE_STT", True)
    def test_stack_health_stt_disabled(self) -> None:
        self.assertEqual(stack_health_stt_entry()["status"], "disabled")

    @patch("app.openrouter_audio.DISABLE_TTS", True)
    def test_stack_health_tts_disabled(self) -> None:
        self.assertEqual(stack_health_tts_entry()["status"], "disabled")

    @patch("app.clients.DISABLE_STT", True)
    def test_call_stt_disabled_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            call_stt(b"x")
        self.assertEqual(str(ctx.exception), "stt_disabled")

    @patch("app.clients.DISABLE_TTS", True)
    def test_call_tts_disabled_returns_empty(self) -> None:
        self.assertEqual(call_tts("x"), "")


if __name__ == "__main__":
    unittest.main()
