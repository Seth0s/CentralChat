"""Phase 0 — context types and config (no HTTP behaviour change)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.context.config import (
    ContextSystemSettings,
    compute_compact_threshold_tokens,
    load_context_settings,
)
from app.context.types import (
    CompactionJob,
    PromptPackage,
    PromptSection,
    PromptSectionKind,
    SessionEvent,
    SessionEventType,
    TokenAccounting,
)


class TestCompactThreshold(unittest.TestCase):
    def test_default_formula(self) -> None:
        # (200_000 - 16_384 - 0) * 0.75 = 137_712
        self.assertEqual(
            compute_compact_threshold_tokens(
                context_window_cap=200_000,
                reserved_output_tokens=16_384,
                reserved_injection_tokens=0,
                compact_threshold_ratio=0.75,
            ),
            137_712,
        )

    def test_with_injection_reserve(self) -> None:
        self.assertEqual(
            compute_compact_threshold_tokens(
                context_window_cap=200_000,
                reserved_output_tokens=16_384,
                reserved_injection_tokens=10_000,
                compact_threshold_ratio=0.75,
            ),
            130_212,
        )

    def test_usable_non_positive_returns_zero(self) -> None:
        self.assertEqual(
            compute_compact_threshold_tokens(
                context_window_cap=10_000,
                reserved_output_tokens=12_000,
                reserved_injection_tokens=0,
                compact_threshold_ratio=0.75,
            ),
            0,
        )


class TestContextSystemSettings(unittest.TestCase):
    def test_defaults_match_roadmap(self) -> None:
        s = ContextSystemSettings()
        self.assertEqual(s.context_window_cap, 200_000)
        self.assertEqual(s.compact_threshold_ratio, 0.75)
        self.assertEqual(s.reserved_output_tokens, 16_384)
        self.assertEqual(s.compact_threshold_tokens, 137_712)
        self.assertEqual(s.embedding_backend, "local")
        self.assertEqual(s.embedding_model_id, "miniLM-L6-v2")
        self.assertEqual(s.rag_namespaces, ("product", "session", "document"))
        self.assertTrue(s.rag_tools_only_via_retrieval)
        self.assertEqual(s.stream_failure_policy, "cancel_no_persist")

    def test_invalid_ratio_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ContextSystemSettings(compact_threshold_ratio=0.01)

    def test_invalid_embedding_backend(self) -> None:
        with self.assertRaises(ValidationError):
            ContextSystemSettings(embedding_backend="openai")

    def test_reserves_exceeding_cap_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ContextSystemSettings(
                context_window_cap=20_000,
                reserved_output_tokens=25_000,
            )


class TestLoadContextSettings(unittest.TestCase):
    def test_load_from_environ(self) -> None:
        env = {
            "CENTRAL_CONTEXT_WINDOW_CAP": "100000",
            "CENTRAL_COMPACT_THRESHOLD_RATIO": "0.8",
            "CENTRAL_RESERVED_OUTPUT_TOKENS": "8192",
            "CENTRAL_RESERVED_INJECTION_TOKENS": "5000",
            "CENTRAL_EMBEDDING_BACKEND": "hash",
            "CENTRAL_EMBEDDING_MODEL_ID": "test-model",
            "CENTRAL_RAG_NAMESPACES": "product,document",
            "CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL": "0",
            "MEMORY_ENABLED": "0",
            "MEMORY_DB_URL": "postgresql://test/db",
        }
        s = load_context_settings(environ=env)
        self.assertEqual(s.context_window_cap, 100_000)
        self.assertEqual(s.compact_threshold_ratio, 0.8)
        self.assertEqual(s.reserved_output_tokens, 8192)
        self.assertEqual(s.reserved_injection_tokens, 5000)
        self.assertEqual(s.embedding_backend, "hash")
        self.assertEqual(s.embedding_model_id, "test-model")
        self.assertEqual(s.rag_namespaces, ("product", "document"))
        self.assertFalse(s.rag_tools_only_via_retrieval)
        self.assertFalse(s.memory_enabled)
        self.assertEqual(s.memory_db_url, "postgresql://test/db")
        # (100000 - 8192 - 5000) * 0.8 = 69446
        self.assertEqual(s.compact_threshold_tokens, 69_446)

    def test_runtime_injection_override(self) -> None:
        s = load_context_settings(reserved_injection_tokens=12_000)
        self.assertEqual(s.reserved_injection_tokens, 12_000)
        self.assertEqual(s.compact_threshold_tokens, 137_712 - int(12_000 * 0.75))


class TestContextTypes(unittest.TestCase):
    def test_session_event_serializes_type_alias(self) -> None:
        ev = SessionEvent(
            tenant_id="t1",
            session_id="sess-12345678",
            event_type=SessionEventType.USER_MESSAGE,
            payload={"content": "hello"},
            ts=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            event_id="e1",
        )
        dumped = ev.model_dump(mode="json", by_alias=True)
        self.assertEqual(dumped["type"], "user_message")
        self.assertEqual(dumped["payload"]["content"], "hello")

    def test_prompt_package_frozen_sections(self) -> None:
        acct = TokenAccounting(
            context_window_cap=200_000,
            reserved_output_tokens=16_384,
            reserved_injection_tokens=0,
            compact_threshold_tokens=137_712,
            section_tokens={"context_session": 1200},
        )
        pkg = PromptPackage(
            sections=(
                PromptSection(
                    kind=PromptSectionKind.SYSTEM_CORE,
                    content="core",
                    token_count=100,
                    cacheable=True,
                ),
            ),
            history=({"role": "user", "content": "hi"},),
            user_text="hi",
            token_accounting=acct,
        )
        self.assertEqual(len(pkg.sections), 1)
        self.assertEqual(pkg.history[0]["role"], "user")
        self.assertEqual(pkg.token_accounting.compact_threshold_tokens, 137_712)

    def test_compaction_job_defaults(self) -> None:
        job = CompactionJob(tenant_id="t1", session_id="sess-12345678")
        self.assertEqual(job.status, "pending")
        self.assertIsNone(job.summary_version)


if __name__ == "__main__":
    unittest.main()
