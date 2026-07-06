"""Git read-only metadata for workspace context (pipeline L2)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_COMMITS = 5
_DEFAULT_MAX_DIRTY = 20


def collect_git_metadata(
    workspace_root: str,
    *,
    max_commits: int = _DEFAULT_MAX_COMMITS,
    max_dirty: int = _DEFAULT_MAX_DIRTY,
) -> dict[str, Any]:
    """Read-only git snapshot: branch, dirty files, recent commits."""
    root = Path(workspace_root).expanduser().resolve()
    meta: dict[str, Any] = {
        "branch": "unknown",
        "dirty_count": 0,
        "dirty_files": [],
        "recent_commits": [],
        "is_git": False,
    }
    if not (root / ".git").is_dir():
        return meta

    meta["is_git"] = True
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if branch.returncode == 0 and branch.stdout.strip():
            meta["branch"] = branch.stdout.strip()

        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if status.returncode == 0:
            dirty: list[str] = []
            for line in status.stdout.splitlines():
                entry = line[3:].strip() if len(line) > 3 else line.strip()
                if entry:
                    dirty.append(entry)
            meta["dirty_count"] = len(dirty)
            meta["dirty_files"] = dirty[: max(0, max_dirty)]

        log_proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                f"-{max(1, max_commits)}",
                "--oneline",
                "--no-decorate",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if log_proc.returncode == 0:
            commits = [ln.strip() for ln in log_proc.stdout.splitlines() if ln.strip()]
            meta["recent_commits"] = commits[: max(1, max_commits)]
    except Exception:
        logger.debug("git metadata failed for %s", workspace_root, exc_info=True)
    return meta


def format_repo_context_block(*, workspace_path: str, git_meta: dict[str, Any]) -> str:
    """System message body for ContextPipeline L2."""
    lines = [
        "[WORKSPACE L2]",
        f"path={workspace_path}",
    ]
    if not git_meta.get("is_git"):
        lines.append("repo=not_a_git_repository")
        return "\n".join(lines)

    lines.append("[REPO_CONTEXT]")
    lines.append(f"branch={git_meta.get('branch', 'unknown')}")
    lines.append(f"dirty_count={git_meta.get('dirty_count', 0)}")

    dirty_files = git_meta.get("dirty_files")
    if isinstance(dirty_files, list) and dirty_files:
        lines.append("dirty_files=" + ", ".join(str(f) for f in dirty_files[:20]))

    commits = git_meta.get("recent_commits")
    if isinstance(commits, list) and commits:
        lines.append("recent_commits:")
        for c in commits:
            lines.append(f"  - {c}")

    return "\n".join(lines)
