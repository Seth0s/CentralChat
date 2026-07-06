"""T6 — OpenRouter Resiliência: Circuit Breaker + Model Fallback.

Circuit breaker: closed → open (after N consecutive failures) → half_open (probe).
Fallback chain: tries primary model, then each fallback in order.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════


class CircuitState:
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # failing fast
    HALF_OPEN = "half_open"  # probing


@dataclass
class CircuitBreaker:
    """Per-backend circuit breaker with configurable thresholds."""

    name: str
    failure_threshold: int = 5  # consecutive failures to open
    recovery_timeout: float = 30.0  # seconds before half_open probe
    half_open_max_requests: int = 1  # probe requests in half_open

    _state: str = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def call(self, fn: Callable[[], Any], fallback: Callable[[], Any] | None = None) -> Any:
        """
        Execute fn() through the circuit breaker.
        Returns fn() result on success, raises CircuitOpenError if open,
        or calls fallback() if provided and circuit is open.
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_count = 0
                    logger.info("circuit_breaker name=%s half_open", self.name)
                else:
                    if fallback:
                        return fallback()
                    raise CircuitOpenError(
                        f"Circuit {self.name} is OPEN. Retry in {self.recovery_timeout:.0f}s."
                    )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_count >= self.half_open_max_requests:
                    if fallback:
                        return fallback()
                    raise CircuitOpenError(f"Circuit {self.name} probing exhausted.")

        try:
            result = fn()
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("circuit_breaker name=%s closed (recovered)", self.name)
            self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_count += 1
                self._state = CircuitState.OPEN
                logger.info("circuit_breaker name=%s open (half_open failed)", self.name)
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker name=%s open failure_count=%s",
                    self.name,
                    self._failure_count,
                )

    def reset(self) -> None:
        """Force reset to closed (for tests)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_count = 0


class CircuitOpenError(RuntimeError):
    """Raised when circuit is open and no fallback is provided."""
    pass


# ═══════════════════════════════════════════════════════════════════
# MODEL FALLBACK CHAIN
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ModelFallbackEntry:
    """A model in the fallback chain."""

    profile: str
    model_override: str | None = None
    circuit_breaker: CircuitBreaker | None = None


class ModelFallbackChain:
    """Tries primary model, then fallback chain on failure."""

    def __init__(self, primary: ModelFallbackEntry, fallbacks: list[ModelFallbackEntry]) -> None:
        self.primary = primary
        self.fallbacks = fallbacks

    def execute(
        self,
        call_fn: Callable[[str, str | None], Any],
    ) -> tuple[Any, str, str | None]:
        """
        Execute call_fn(profile, model_override) through the chain.
        Returns (result, profile_used, model_override_used).

        Raises RuntimeError if all entries fail.
        """
        entries = [self.primary] + self.fallbacks
        last_error: Exception | None = None

        for i, entry in enumerate(entries):
            cb = entry.circuit_breaker
            if cb and cb.state == CircuitState.OPEN:
                logger.debug("fallback_skip name=%s circuit_open", entry.profile)
                continue

            try:
                if cb:
                    result = cb.call(
                        lambda: call_fn(entry.profile, entry.model_override),
                    )
                else:
                    result = call_fn(entry.profile, entry.model_override)

                logger.info(
                    "fallback_used profile=%s attempt=%s/%s",
                    entry.profile,
                    i + 1,
                    len(entries),
                )
                return result, entry.profile, entry.model_override

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "fallback_failed profile=%s attempt=%s/%s err=%s",
                    entry.profile,
                    i + 1,
                    len(entries),
                    exc,
                )
                continue

        raise RuntimeError(
            f"All {len(entries)} model fallbacks exhausted. Last error: {last_error}"
        )


# ═══════════════════════════════════════════════════════════════════
# SINGLETON CIRCUIT BREAKERS
# ═══════════════════════════════════════════════════════════════════

# One circuit breaker per backend/service
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name=name)
        return _breakers[name]


def reset_all_circuit_breakers() -> None:
    """Reset all circuit breakers (for tests)."""
    with _breakers_lock:
        for cb in _breakers.values():
            cb.reset()


# ── Default OpenRouter circuit breaker ──
_openrouter_cb = get_circuit_breaker("openrouter")


def call_with_circuit_breaker(
    fn: Callable[[], Any],
    fallback: Callable[[], Any] | None = None,
) -> Any:
    """Execute fn() through the default OpenRouter circuit breaker."""
    return _openrouter_cb.call(fn, fallback=fallback)
