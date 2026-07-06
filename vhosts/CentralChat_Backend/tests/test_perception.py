"""ADR-016 — multimodal perception (vision / audio)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.modality_models import ROLE_VIDEO_PERCEIVE, ROLE_VISION_PERCEIVE, clear_modality_models_cache
from app.perception import (
    MediaAttachment,
    build_perception_enriched_block,
    resolve_perception_call_params,
    resolve_perception_modality_role,
)


class TestPerception(unittest.TestCase):
    def tearDown(self) -> None:
        clear_modality_models_cache()

    def test_resolve_role_video(self) -> None:
        vid = MediaAttachment(kind="video", mime="video/mp4", data_base64="v" * 32)
        self.assertEqual(resolve_perception_modality_role([vid]), ROLE_VIDEO_PERCEIVE)

    def test_resolve_role_image_vs_audio(self) -> None:
        img = MediaAttachment(kind="image", mime="image/png", data_base64="a" * 16)
        aud = MediaAttachment(kind="audio", mime="audio/wav", data_base64="b" * 16)
        self.assertEqual(
            resolve_perception_modality_role([img]),
            ROLE_VISION_PERCEIVE,
        )
        self.assertEqual(
            resolve_perception_modality_role([aud]),
            "audio_perceive",
        )
        self.assertEqual(
            resolve_perception_modality_role([img, aud]),
            ROLE_VISION_PERCEIVE,
        )

    @patch("app.perception.call_model_router_raw_messages", return_value="uma cena.")
    @patch("app.perception.MODEL_ROUTER_URL", "http://mr:8005")
    @patch(
        "app.perception.resolve_modality_call_params",
        return_value=("cloud_gemini", "google/gemma-4-26b-a4b-it:free"),
    )
    def test_png_block_uses_configured_model_label(
        self,
        _resolve: object,
        _mock_router: object,
    ) -> None:
        att = MediaAttachment(kind="image", mime="image/png", data_base64="a" * 32)
        block = build_perception_enriched_block("descreve", [att])
        self.assertTrue(block.startswith("[Percepção gemma-4-26b-a4b-it:free]"))
        self.assertIn("uma cena.", block)

    @patch("app.perception.call_model_router_raw_messages", return_value="transcrito.")
    @patch("app.perception.MODEL_ROUTER_URL", "http://mr:8005")
    @patch(
        "app.perception.resolve_modality_call_params",
        return_value=("cloud_gemini", "google/gemma-4-26b-a4b-it:free"),
    )
    def test_audio_sends_input_audio_part(self, _resolve: object, mock_call: object) -> None:
        att = MediaAttachment(kind="audio", mime="audio/wav", data_base64="Y" * 32)
        build_perception_enriched_block("ouve", [att])
        _args, kwargs = mock_call.call_args
        messages = _args[0]
        content = messages[0]["content"]
        audio_parts = [p for p in content if p.get("type") == "input_audio"]
        self.assertEqual(len(audio_parts), 1)
        self.assertEqual(audio_parts[0]["input_audio"]["format"], "wav")
        self.assertEqual(kwargs.get("allowlist_mode"), "modality")

    @patch("app.perception.resolve_modality_call_params")
    def test_resolve_perception_call_params_delegates(self, mock_rpc: object) -> None:
        mock_rpc.return_value = ("cloud_gemini", "vendor/model-x")
        att = MediaAttachment(kind="image", mime="image/png", data_base64="c" * 16)
        role, prof, mid = resolve_perception_call_params([att])
        self.assertEqual(role, ROLE_VISION_PERCEIVE)
        self.assertEqual(prof, "cloud_gemini")
        self.assertEqual(mid, "vendor/model-x")
        mock_rpc.assert_called_once_with(ROLE_VISION_PERCEIVE)

    @patch("app.perception._build_video_perception_block", return_value="[Percepção vídeo mock]\nresumo.")
    @patch("app.perception.MODEL_ROUTER_URL", "http://mr:8005")
    def test_video_delegates_to_frame_pipeline(self, mock_vid: object) -> None:
        att = MediaAttachment(kind="video", mime="video/mp4", data_base64="d" * 32)
        block = build_perception_enriched_block("resume o clip", [att])
        mock_vid.assert_called_once()
        self.assertIn("resumo", block)

    @patch("app.perception.call_model_router_raw_messages")
    @patch("app.perception.extract_video_frames_base64", return_value=["a" * 40, "b" * 40])
    @patch("app.perception.ffmpeg_available", return_value=True)
    @patch("app.perception.MODEL_ROUTER_URL", "http://mr:8005")
    @patch(
        "app.perception.resolve_modality_call_params",
        side_effect=[
            ("cloud_gemini", "vision-model"),
            ("cloud_gemini", "video-model"),
        ],
    )
    def test_video_does_not_send_raw_video_to_llm(
        self,
        _rpc: object,
        _ff: object,
        mock_frames: object,
        mock_call: object,
    ) -> None:
        mock_call.side_effect = ["frame um", "frame dois", "resumo final"]
        att = MediaAttachment(kind="video", mime="video/mp4", data_base64="x" * 64)
        block = build_perception_enriched_block("o que acontece?", [att])
        self.assertIn("resumo final", block)
        for _args, kwargs in mock_call.call_args_list:
            messages = _args[0]
            content = messages[0]["content"]
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        url = str(part.get("image_url", {}).get("url", ""))
                        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
                        self.assertNotIn("video/mp4", url)
            elif isinstance(content, str):
                self.assertNotIn("x" * 64, content)


if __name__ == "__main__":
    unittest.main()
