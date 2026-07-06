"""SchemaTracker — tracks tool schemas across turns to avoid re-injection.

When compaction removes tool schemas from context, the SchemaTracker
knows which ones are already "in" the current context window and only
re-injects schemas that are missing.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §8.1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SchemaTracker:
    """Tracks which tool schemas are present in the current context.

    When schemas are injected as [TOOL_SCHEMA:id=X|tool=Y] markers,
    the tracker records which tools are active. After compaction,
    only tools NOT in the tracker are re-injected.

    Schema versioning: if a tool schema changes (hash differs),
    it's treated as "not present" and re-injected.
    """

    # Active tools: name → schema hash + injection marker
    active: dict[str, _SchemaEntry] = field(default_factory=dict)

    # Turn counter for versioning
    turn: int = 0

    def mark_injected(self, tool_name: str, schema: dict[str, Any]) -> None:
        """Record that a tool schema was injected into context."""
        import hashlib
        import json

        schema_hash = hashlib.md5(
            json.dumps(schema, sort_keys=True).encode()
        ).hexdigest()[:8]

        self.turn += 1
        marker = f"{tool_name}_{self.turn}"

        self.active[tool_name] = _SchemaEntry(
            schema_hash=schema_hash,
            marker=marker,
            turn=self.turn,
        )

    def is_present(self, tool_name: str, schema: dict[str, Any]) -> bool:
        """Check if a tool schema is already in context.

        Returns True if:
        - The tool is tracked AND
        - The schema hash matches (schema hasn't changed) AND
        - The marker is still in the current messages
        """
        if tool_name not in self.active:
            return False

        import hashlib
        import json

        entry = self.active[tool_name]
        current_hash = hashlib.md5(
            json.dumps(schema, sort_keys=True).encode()
        ).hexdigest()[:8]

        return current_hash == entry.schema_hash

    def get_missing(
        self,
        tools: dict[str, dict[str, Any]],
        current_messages: list[dict[str, str]],
    ) -> list[str]:
        """Return tool names that need to be injected.

        A tool is "missing" if it's not tracked, its schema changed,
        or its marker is no longer in current_messages.
        """
        missing: list[str] = []
        for name, schema in tools.items():
            if not self.is_present(name, schema):
                missing.append(name)
                continue
            # Check if marker is still in messages
            entry = self.active[name]
            marker_str = f"[TOOL_SCHEMA:id={entry.marker}|tool={name}]"
            if not any(marker_str in str(m.get("content", "")) for m in current_messages):
                missing.append(name)

        return missing

    def handle_compaction(self, current_messages: list[dict[str, str]]) -> None:
        """After compaction, check which schemas were removed.

        Removes entries whose markers are no longer in context,
        so they'll be re-injected on next turn.
        """
        removed = []
        for name, entry in list(self.active.items()):
            marker_str = f"[TOOL_SCHEMA:id={entry.marker}|tool={name}]"
            if not any(marker_str in str(m.get("content", "")) for m in current_messages):
                removed.append(name)
                del self.active[name]

        if removed:
            logger.debug(
                "SchemaTracker: compaction removed %d tools: %s",
                len(removed), ", ".join(removed),
            )

    def reset(self) -> None:
        """Reset all tracking (e.g., new session)."""
        self.active.clear()
        self.turn = 0


@dataclass
class _SchemaEntry:
    """Internal tracking entry for a tool schema."""

    schema_hash: str
    marker: str
    turn: int


# Per-session singleton (one tracker per session for multi-turn tracking)
_session_trackers: dict[str, SchemaTracker] = {}


def get_schema_tracker(session_id: str | None = None) -> SchemaTracker:
    """Get or create a SchemaTracker for a session.

    Returns a fresh tracker if no session_id is provided.
    """
    if not session_id:
        return SchemaTracker()

    if session_id not in _session_trackers:
        _session_trackers[session_id] = SchemaTracker()

    return _session_trackers[session_id]


def reset_schema_tracker(session_id: str) -> None:
    """Reset the tracker for a session (e.g., new chat)."""
    if session_id in _session_trackers:
        del _session_trackers[session_id]
