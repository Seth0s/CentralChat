"""Workspace path guard — anti traversal for MVP file tools."""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceGuardError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize_workspace_root(raw: str) -> str:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkspaceGuardError("workspace_not_directory")
    return str(root)


def normalize_workspace_path_for_bind(raw: str) -> str:
    """Accept client-side workspace path for POST /ui/workspace.

    The orchestrator may run in Docker while the daemon uses this path on the host.
    We only normalize to an absolute path — no is_dir() on the server filesystem.
    """
    text = (raw or "").strip()
    if not text or "\x00" in text:
        raise WorkspaceGuardError("empty_path")
    root = Path(text).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return str(root.resolve(strict=False))


def resolve_workspace_path(*, workspace_root: str, path: str) -> str:
    """Resolve ``path`` (absolute or relative to root) inside workspace_root."""
    root = Path(normalize_workspace_root(workspace_root))
    raw = (path or "").strip()
    if not raw:
        raise WorkspaceGuardError("empty_path")
    if "\x00" in raw:
        raise WorkspaceGuardError("invalid_path")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceGuardError("path_outside_workspace") from exc
    return str(resolved)
