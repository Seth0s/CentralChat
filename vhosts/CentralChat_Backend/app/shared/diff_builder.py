"""Unified diff builder for MVP file approvals."""

from __future__ import annotations

import difflib


def build_unified_diff(
    *,
    path: str,
    old_content: str,
    new_content: str,
    context_lines: int = 3,
) -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    if not old_lines and old_content:
        old_lines = [old_content]
    if not new_lines and new_content:
        new_lines = [new_content]
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )
    return "".join(diff)


def diff_summary(diff_text: str) -> str:
    adds = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    dels = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return f"+{adds} -{dels} lines"
