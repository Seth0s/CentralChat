from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ContextStats:
    history_messages_before: int
    history_messages_after: int
    history_chars_before: int
    history_chars_after: int
    compacted: bool
    summary_chars: int
    summary_provenance: str | None = None
    summary_version: int | None = None
    verbatim_tokens_before: int = 0
    verbatim_tokens_after: int = 0
    compaction_mode: str | None = None


def _count_chars(history: list[dict[str, str]]) -> int:
    return sum(len(m.get("content", "") or "") for m in history)


def _is_over_limits(history: list[dict[str, str]], *, after_messages: int, after_chars: int) -> bool:
    if after_messages > 0 and len(history) >= after_messages:
        return True
    if after_chars > 0 and _count_chars(history) >= after_chars:
        return True
    return False


def load_last_summary(path: str) -> str | None:
    try:
        if not path or not os.path.exists(path):
            return None
        raw = json.loads(open(path, encoding="utf-8").read())
        s = raw.get("summary")
        return str(s) if s else None
    except Exception:
        return None


def save_last_summary(path: str, summary: str, *, request_id: str, provenance: str | None = None) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "request_id": request_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "provenance": provenance or "unknown",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def prepare_history(
    *,
    history: list[dict[str, str]],
    request_id: str,
    compact_after_messages: int,
    compact_after_chars: int,
    keep_last_messages: int,
    summary_store_path: str,
    summarizer: Any | None,
    summary_provenance: str | None = None,
) -> tuple[list[dict[str, str]], ContextStats, str | None]:
    """
    Returns (new_history, stats, summary_used_or_created).

    summarizer: callable(old_messages:list[dict]) -> str (eco summarizer via model-router).
    """
    before_msgs = len(history)
    before_chars = _count_chars(history)

    if not _is_over_limits(history, after_messages=compact_after_messages, after_chars=compact_after_chars):
        return (
            history,
            ContextStats(
                history_messages_before=before_msgs,
                history_messages_after=before_msgs,
                history_chars_before=before_chars,
                history_chars_after=before_chars,
                compacted=False,
                summary_chars=0,
                summary_provenance=None,
            ),
            None,
        )

    keep = max(0, int(keep_last_messages))
    recent = history[-keep:] if keep else []
    older = history[: max(0, len(history) - len(recent))]

    # Try to summarize older chunk.
    summary = None
    if callable(summarizer) and older:
        try:
            summary = str(summarizer(older)).strip() or None
        except Exception:
            summary = None

    # If summarizer failed, fall back to last stored summary (better than nothing).
    if not summary:
        summary = load_last_summary(summary_store_path)

    new_history = list(recent)
    prov_label = summary_provenance or "eco_summarizer"
    if summary:
        summary_msg = {
            "role": "system",
            "content": "Memory summary (compacted history):\n" + summary,
        }
        new_history = [summary_msg, *recent]
        save_last_summary(summary_store_path, summary, request_id=request_id, provenance=prov_label)

    after_msgs = len(new_history)
    after_chars = _count_chars(new_history)
    stats = ContextStats(
        history_messages_before=before_msgs,
        history_messages_after=after_msgs,
        history_chars_before=before_chars,
        history_chars_after=after_chars,
        compacted=True,
        summary_chars=len(summary or ""),
        summary_provenance=prov_label if summary else None,
    )
    return new_history, stats, summary

