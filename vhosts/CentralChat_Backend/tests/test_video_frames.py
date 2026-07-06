"""ADR-016 §13 — video frame extraction."""
from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from app.video_frames import extract_video_frames_base64, ffmpeg_available


class TestVideoFrames(unittest.TestCase):
    def test_ffmpeg_available_is_bool(self) -> None:
        self.assertIsInstance(ffmpeg_available(), bool)

    @patch("app.video_frames.ffmpeg_available", return_value=False)
    def test_raises_when_ffmpeg_missing(self, *_m: object) -> None:
        with self.assertRaises(ValueError) as ctx:
            extract_video_frames_base64("Y" * 32, mime="video/mp4")
        self.assertIn("ffmpeg_not_available", str(ctx.exception))

    @patch("app.video_frames.subprocess.run")
    @patch("app.video_frames.ffmpeg_available", return_value=True)
    def test_extract_returns_jpeg_frames(self, _ff: object, mock_run: object) -> None:
        def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            from pathlib import Path

            inp_idx = cmd.index("-i") + 1
            td_path = Path(cmd[inp_idx]).parent
            (td_path / "frame_001.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            (td_path / "frame_002.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            class _Proc:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Proc()

        mock_run.side_effect = _fake_run
        frames = extract_video_frames_base64(
            base64.b64encode(b"fake-mp4-bytes-xx").decode("ascii"),
            mime="video/mp4",
            max_frames=2,
        )
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(len(f) >= 4 for f in frames))
