"""Token counter — accurate token estimation using tiktoken.

Replaces the chars/4 fallback with real token counts using
the cl100k_base encoding (GPT-4, GPT-3.5-turbo, text-embedding-3).

Falls back to chars/4 if tiktoken is not available.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Fallback ratio when tiktoken is unavailable
_CHARS_PER_TOKEN = 4


@lru_cache(maxsize=1)
def _get_encoding():
    """Lazy-load tiktoken encoding (cached)."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        logger.debug("tiktoken not installed — using chars/4 fallback")
        return None
    except Exception:
        logger.debug("tiktoken encoding failed — using chars/4 fallback", exc_info=True)
        return None


class TokenCounter:
    """Accurate token counter using tiktoken with chars/4 fallback."""

    def __init__(self) -> None:
        self._enc = _get_encoding()

    @property
    def available(self) -> bool:
        """True if tiktoken is available for accurate counting."""
        return self._enc is not None

    def count(self, text: str) -> int:
        """Count tokens in a text string."""
        if not text:
            return 0
        if self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:
                logger.debug("Token encode failed", exc_info=True)
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens across a list of messages.

        Uses the chat message token counting formula:
        - Each message: 4 tokens for role + content separators
        - Plus the content tokens
        - Plus 3 tokens for the overall framing
        """
        if not messages:
            return 0

        total = 0
        for msg in messages:
            # Message framing: <im_start>role\ncontent<im_end>
            total += 4  # per-message framing tokens
            for key in ("content", "name"):
                value = msg.get(key, "")
                if value:
                    total += self.count(str(value))
        total += 3  # final framing tokens
        return total

    def count_tools(self, tools: list[dict[str, Any]]) -> int:
        """Count tokens for tool schemas."""
        if not tools:
            return 0
        import json

        total = 0
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})

            total += self.count(name)
            total += self.count(desc)
            if params:
                total += self.count(json.dumps(params, sort_keys=True))

        # Tools framing: ~5 tokens for the tools block itself
        total += 5
        return total


# Singleton instance
_default_counter: TokenCounter | None = None


def get_token_counter() -> TokenCounter:
    """Get the default TokenCounter instance."""
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter()
    return _default_counter


def count_tokens(text: str) -> int:
    """Convenience: count tokens in text."""
    return get_token_counter().count(text)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Convenience: count tokens across messages."""
    return get_token_counter().count_messages(messages)
