"""
Turn file log — tracks original content of files mutated during an agent turn.
Supports /undo: restores all files touched in the current turn to their pre-turn state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileSnapshot:
    path: str
    original_content: str | None  # None = file didn't exist before
    mutated: bool = True


@dataclass
class TurnFileLog:
    """Per-request log of file snapshots taken before mutations."""

    snapshots: dict[str, FileSnapshot] = field(default_factory=dict)

    def snapshot_before_mutate(self, path: str) -> None:
        """Save original content before mutation. Call once per unique file per turn."""
        if path in self.snapshots:
            return  # already saved
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except Exception:
                content = None
        else:
            content = None  # file doesn't exist yet
        self.snapshots[path] = FileSnapshot(path=path, original_content=content)

    def undo(self) -> dict[str, Any]:
        """Restore all snapshotted files to their original state. Returns summary."""
        restored: list[str] = []
        deleted: list[str] = []
        failed: list[dict[str, str]] = []

        for path, snap in self.snapshots.items():
            try:
                if snap.original_content is None:
                    # File didn't exist before — delete it
                    if os.path.isfile(path):
                        os.remove(path)
                        deleted.append(path)
                else:
                    # Restore original content
                    parent = os.path.dirname(path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(snap.original_content)
                    restored.append(path)
            except Exception as exc:
                failed.append({"path": path, "error": str(exc)[:200]})

        self.snapshots.clear()
        return {
            "ok": len(failed) == 0,
            "files_restored": len(restored),
            "files_deleted": len(deleted),
            "restored": restored,
            "deleted": deleted,
            "failed": failed,
        }

    def __bool__(self) -> bool:
        return bool(self.snapshots)


# Global store: request_id -> TurnFileLog
_turn_logs: dict[str, TurnFileLog] = {}


def get_turn_log(request_id: str) -> TurnFileLog:
    """Get or create the TurnFileLog for a request."""
    if request_id not in _turn_logs:
        _turn_logs[request_id] = TurnFileLog()
    return _turn_logs[request_id]


def clear_turn_log(request_id: str) -> None:
    """Remove the turn log after undo or new request."""
    _turn_logs.pop(request_id, None)


def undo_turn(request_id: str) -> dict[str, Any]:
    """Execute undo for a request and return summary."""
    log = _turn_logs.pop(request_id, None)
    if log is None or not log.snapshots:
        return {"ok": False, "error": "nothing_to_undo", "request_id": request_id}
    return log.undo()
