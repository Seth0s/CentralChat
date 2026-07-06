"""ADR-017 phase 8 — legacy platform tools and host context gating."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context.sections import build_prefix_sections
from app.old_tools.platform_specs import (
    PLATFORM_TOOL_NAMES,
    merge_legacy_platform_specs,
    strip_platform_specs,
)
from app.platform_context import include_platform_host_context
from app.tool_registry import _build_active_tool_specs


def _noop_loaders() -> dict:
    return {
        "host_summary_loader": lambda _rid: {"ok": True},
        "memory_recall_builder": lambda _p: ([], 0),
        "document_rag_builder": lambda _p: ([], {}),
        "session_rag_builder": lambda _p: ([], {}),
        "product_rag_builder": lambda _p: ([], {}),
        "playbook_builder": lambda _p: None,
        "record_capability_digest": lambda _ep, _n: None,
    }


class TestPlatformSpecs(unittest.TestCase):
    def test_strip_removes_platform_tools(self) -> None:
        specs = {"list_processes": {"name": "list_processes"}, "request_shell": {"name": "request_shell"}}
        out = strip_platform_specs(specs)
        self.assertNotIn("list_processes", out)
        self.assertIn("request_shell", out)

    def test_merge_legacy_restores_subset(self) -> None:
        core = {n: {"name": n} for n in ("list_processes", "request_shell", "client_read_file")}
        merged = merge_legacy_platform_specs(core)
        self.assertIn("list_processes", merged)
        self.assertNotIn("request_shell", merged)
        self.assertNotIn("client_read_file", merged)
        self.assertTrue(PLATFORM_TOOL_NAMES.issuperset(merged.keys()))


class TestActiveToolCatalog(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    def test_tenant_catalog_excludes_platform(self) -> None:
        specs = _build_active_tool_specs()
        self.assertNotIn("list_processes", specs)
        self.assertNotIn("grep_workspace", specs)

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
    def test_legacy_catalog_includes_platform(self) -> None:
        specs = _build_active_tool_specs()
        self.assertIn("list_processes", specs)


class TestPlatformHostContext(unittest.TestCase):
    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.config.CENTRAL_INCLUDE_PLATFORM_CONTEXT", False)
    def test_disabled_by_default(self) -> None:
        self.assertFalse(include_platform_host_context())

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.config.CENTRAL_INCLUDE_PLATFORM_CONTEXT", True)
    def test_enabled_via_env(self) -> None:
        self.assertTrue(include_platform_host_context())

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", True)
    @patch("app.config.CENTRAL_INCLUDE_PLATFORM_CONTEXT", False)
    def test_legacy_forces_host_context(self) -> None:
        self.assertTrue(include_platform_host_context())


class TestHostContextPrefix(unittest.TestCase):
    def _build(self, *, inject: bool) -> tuple[list[dict[str, str]], dict]:
        payload = SimpleNamespace(
            text="cpu?",
            history=[],
            chat_session_id=None,
            include_long_session_memory=False,
            include_memory_recall=False,
            include_document_rag=False,
            document_rag_doc_id=None,
            include_session_rag=False,
            include_playbook=False,
            include_capability_digest=False,
            widget_active_slot=None,
        )
        loaders = _noop_loaders()
        prefix, _sections, meta, _ = build_prefix_sections(
            payload,
            inject_host_context=inject,
            host_summary_loader=loaders["host_summary_loader"],
            request_id="rid-phase8",
            multislot_system_msg=None,
            digest_metrics_endpoint="test",
            record_capability_digest=loaders["record_capability_digest"],
            memory_recall_builder=loaders["memory_recall_builder"],
            document_rag_builder=loaders["document_rag_builder"],
            session_rag_builder=loaders["session_rag_builder"],
            product_rag_builder=loaders["product_rag_builder"],
            playbook_builder=loaders["playbook_builder"],
            system_prompt_enabled=False,
            pre_injection_enabled=False,
            pre_injection_file_path=None,
            capability_digest_env_enabled=False,
            focus_mode=True,
        )
        return prefix, meta

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.config.CENTRAL_INCLUDE_PLATFORM_CONTEXT", False)
    def test_skips_host_block_when_platform_disabled(self) -> None:
        prefix, meta = self._build(inject=True)
        joined = "\n".join(m.get("content", "") for m in prefix)
        self.assertNotIn("[FACTUAL_HOST_CONTEXT", joined)
        self.assertFalse(meta.get("host_context_block_applied"))
        self.assertTrue(meta.get("host_context_skipped_platform_disabled"))

    @patch("app.config.CENTRAL_LEGACY_PLATFORM_TOOLS", False)
    @patch("app.config.CENTRAL_INCLUDE_PLATFORM_CONTEXT", True)
    def test_applies_host_block_when_enabled(self) -> None:
        prefix, meta = self._build(inject=True)
        joined = "\n".join(m.get("content", "") for m in prefix)
        self.assertIn("[FACTUAL_HOST_CONTEXT", joined)
        self.assertTrue(meta.get("host_context_block_applied"))


if __name__ == "__main__":
    unittest.main()
