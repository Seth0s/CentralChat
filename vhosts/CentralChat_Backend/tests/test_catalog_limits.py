"""Tests for catalog prompt limits."""

from __future__ import annotations

import os

import pytest

from app.shared.catalog_limits import (
    _DEFAULT_PROMPT_MAX_CHARS,
    catalog_prompt_max_chars,
    truncate_catalog_prompt,
)


def test_default_prompt_max_is_64k():
    assert _DEFAULT_PROMPT_MAX_CHARS == 64_000
    assert catalog_prompt_max_chars() == 64_000


def test_truncate_respects_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CENTRAL_CATALOG_PROMPT_MAX_CHARS", "100")
    assert catalog_prompt_max_chars() == 1000  # min floor
    monkeypatch.setenv("CENTRAL_CATALOG_PROMPT_MAX_CHARS", "5000")
    assert catalog_prompt_max_chars() == 5000
    assert len(truncate_catalog_prompt("x" * 10_000)) == 5000
    assert truncate_catalog_prompt(None) == ""


def test_invalid_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CENTRAL_CATALOG_PROMPT_MAX_CHARS", "not-a-number")
    assert catalog_prompt_max_chars() == _DEFAULT_PROMPT_MAX_CHARS


def test_empty_env_uses_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CENTRAL_CATALOG_PROMPT_MAX_CHARS", raising=False)
    assert catalog_prompt_max_chars() == _DEFAULT_PROMPT_MAX_CHARS
