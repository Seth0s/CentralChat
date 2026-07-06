"""Fase 7 — pipeline híbrido com mocks."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.assistant_hybrid_pipeline import iter_ndjson_lines_with_stream_fallback, record_pipeline_decision


class TestHybridStreamFallback(unittest.TestCase):
    def test_retries_next_profile_when_error_before_token(self) -> None:
        decisions: list[dict] = []

        def fake_lines(
            _message: str,
            _history: list[dict[str, str]],
            *,
            profile: str,
            model_override: str | None = None,
        ):
            if profile == "first":
                yield json.dumps({"e": "error", "message": "upstream"}) + "\n"
                return
            yield json.dumps({"e": "token", "d": "OK"}) + "\n"
            yield json.dumps({"e": "done"}) + "\n"

        with patch(
            "app.assistant_hybrid_pipeline.build_stream_fallback_attempts",
            return_value=[("first", None, "a"), ("second", None, "b")],
        ):
            out = list(
                iter_ndjson_lines_with_stream_fallback(
                    "x",
                    [],
                    primary_profile="first",
                    primary_model_override=None,
                    decisions_out=decisions,
                    stream_lines=fake_lines,
                )
            )
        self.assertTrue(any("OK" in x for x in out))
        phases = [d.get("phase") for d in decisions]
        self.assertIn("ndjson_error_before_token", phases)
        self.assertIn("stream_success", phases)

    def test_no_retry_after_token(self) -> None:
        decisions: list[dict] = []

        def fake_lines(
            _message: str,
            _history: list[dict[str, str]],
            *,
            profile: str,
            model_override: str | None = None,
        ):
            yield json.dumps({"e": "token", "d": "x"}) + "\n"
            yield json.dumps({"e": "error", "message": "late"}) + "\n"

        with patch(
            "app.assistant_hybrid_pipeline.build_stream_fallback_attempts",
            return_value=[("only", None, "a"), ("second", None, "b")],
        ):
            out = list(
                iter_ndjson_lines_with_stream_fallback(
                    "x",
                    [],
                    primary_profile="only",
                    primary_model_override=None,
                    decisions_out=decisions,
                    stream_lines=fake_lines,
                )
            )
        self.assertEqual(len(out), 2)
        self.assertIn("late", out[1])
        self.assertIn("ndjson_error_final", [d.get("phase") for d in decisions])

    def test_record_pipeline_decision(self) -> None:
        d: list[dict] = []
        record_pipeline_decision(d, phase="x", k=1)
        self.assertEqual(d[0]["phase"], "x")


if __name__ == "__main__":
    unittest.main()
