"""Política L8 pré-Fase 7 — extract, anexos, summarização."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.attachment_policy import validate_media_attachments
from app.l8_pipeline_policy import clear_l8_pipeline_policy_cache, effective_summarization_thresholds
from app.perception import MediaAttachment
from app.router_extract import slim_injected_history_for_router


class TestRouterExtract(unittest.TestCase):
    def test_preserves_prefix_limits_tail(self) -> None:
        prefix = [{"role": "system", "content": "SYS"}]
        tail = [{"role": "user", "content": str(i)} for i in range(10)]
        slim, audit = slim_injected_history_for_router(
            prefix, tail, max_messages=3, max_chars=100_000
        )
        self.assertEqual(slim[0]["content"], "SYS")
        self.assertEqual(len(slim), 4)
        self.assertEqual(audit["tail_messages_after"], 3)


class TestAttachmentPolicy(unittest.TestCase):
    def test_video_mime_allowed_by_default_prefixes(self) -> None:
        att = MediaAttachment(kind="video", mime="video/mp4", data_base64="z" * 24)
        with patch(
            "app.attachment_policy.load_l8_pipeline_policy",
            return_value={
                "attachments": {
                    "max_count": 4,
                    "max_base64_chars_per_item": 4096,
                    "max_video_base64_chars": 1_000_000,
                    "allowed_mime_prefixes": ["image/", "audio/", "video/"],
                }
            },
        ):
            validate_media_attachments([att])

    def test_too_many_videos_rejected(self) -> None:
        v1 = MediaAttachment(kind="video", mime="video/mp4", data_base64="a" * 24)
        v2 = MediaAttachment(kind="video", mime="video/webm", data_base64="b" * 24)
        with patch(
            "app.attachment_policy.load_l8_pipeline_policy",
            return_value={"attachments": {"max_count": 8, "max_video_base64_chars": 1_000_000}},
        ):
            with self.assertRaises(ValueError) as ctx:
                validate_media_attachments([v1, v2])
            self.assertIn("too_many_videos", str(ctx.exception))

    def test_too_many(self) -> None:
        atts = [
            MediaAttachment(mime="image/png", data_base64="x" * 20),
            MediaAttachment(mime="image/png", data_base64="y" * 20),
        ]
        with patch("app.attachment_policy.load_l8_pipeline_policy", return_value={"attachments": {"max_count": 1}}):
            with self.assertRaises(ValueError) as ctx:
                validate_media_attachments(atts)
            self.assertIn("too_many", str(ctx.exception))


class TestSummarizationThresholds(unittest.TestCase):
    def tearDown(self) -> None:
        clear_l8_pipeline_policy_cache()

    def test_min_of_env_and_policy(self) -> None:
        clear_l8_pipeline_policy_cache()

        def fake_load(*, force_reload: bool = False) -> dict:
            return {
                "summarization": {
                    "trigger_messages": 25,
                    "trigger_chars": 200_000,
                    "keep_last_messages": 20,
                    "provenance_label": "aux_llm_resolved",
                },
            }

        with patch.multiple(
            "app.l8_pipeline_policy",
            COMPACT_AFTER_MESSAGES=40,
            COMPACT_AFTER_CHARS=100_000,
            COMPACT_KEEP_LAST_MESSAGES=12,
            load_l8_pipeline_policy=fake_load,
        ):
            m, c, k, p = effective_summarization_thresholds()
            self.assertEqual(m, 25)
            self.assertLessEqual(m, 40)
            self.assertEqual(k, 12)
            self.assertEqual(p, "aux_llm_resolved")


if __name__ == "__main__":
    unittest.main()
