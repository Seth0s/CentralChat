"""ContextEngine step registry — pluggable pipeline steps.

Steps register themselves by name with a phase (resolve/gather/assemble/post)
and a priority (lower = runs first). The registry is a global dict that
can be extended without modifying assistant_routes.py.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §3.2
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol

from app.context_engine.state import ContextState

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Phase
# ═══════════════════════════════════════════════════════════════

class Phase(str, Enum):
    """Execution phases in order."""

    RESOLVE = "resolve"
    """Sync, <5ms: resolve session, work item, active doc, execution mode."""

    GATHER = "gather"
    """Async parallel, ~120ms: system layers, RAG, tool selection."""

    ASSEMBLE = "assemble"
    """Sync, deterministic: merge sections, token budget, build messages."""

    POST = "post"
    """Background: indexing, compaction checkpoint, audit emit."""


PHASE_ORDER: list[Phase] = [Phase.RESOLVE, Phase.GATHER, Phase.ASSEMBLE, Phase.POST]


# ═══════════════════════════════════════════════════════════════
# ContextStep protocol
# ═══════════════════════════════════════════════════════════════

class ContextStep(Protocol):
    """A pluggable step in the context assembly pipeline.

    Each step has:
      - name: unique identifier (e.g. 'resolve.session_history')
      - phase: when it runs (resolve, gather, assemble, post)
      - priority: execution order within phase (lower = first)
      - should_run: gate function (return False to skip)
      - run: mutates ContextState
    """

    name: str
    phase: Phase
    priority: int

    async def should_run(self, state: ContextState) -> bool: ...
    async def run(self, state: ContextState) -> ContextState: ...


# ═══════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════

STEP_REGISTRY: dict[str, ContextStep] = {}
"""Global step registry. Steps register themselves at import time."""


def register_step(step):
    """Register a step in the global registry.

    Accepts either a step instance or a class (auto-instantiated).

    Usage:
        @register_step
        class ResolveSessionHistory:
            name = "resolve.session_history"
            phase = Phase.RESOLVE
            priority = 10
            ...

    Or:
        register_step(MyStep())
    """
    if isinstance(step, type):
        step = step()
    if step.name in STEP_REGISTRY:
        logger.warning("Step %s already registered — overwriting", step.name)
    STEP_REGISTRY[step.name] = step
    logger.debug("Registered step: %s (phase=%s priority=%d)", step.name, step.phase, step.priority)
    return step


def list_steps(phase: Phase | None = None) -> list[ContextStep]:
    """List registered steps, optionally filtered by phase, sorted by priority."""
    steps = list(STEP_REGISTRY.values())
    if phase is not None:
        steps = [s for s in steps if s.phase == phase]
    steps.sort(key=lambda s: (PHASE_ORDER.index(s.phase), s.priority))
    return steps


async def run_phase(phase: Phase, state: ContextState) -> ContextState:
    """Run all registered steps for a given phase in priority order.

    Each step's should_run() is called first. If it returns False,
    the step is skipped.

    Timing is recorded in state.meta[f'step_ms.{step.name}'].

    Returns the (possibly mutated) ContextState.
    """
    steps = list_steps(phase)
    if not steps:
        return state

    for step in steps:
        t0 = time.monotonic()
        try:
            if await step.should_run(state):
                state = await step.run(state)
        except Exception:
            logger.exception("Step %s failed — skipping", step.name)
            state.meta.setdefault("step_errors", []).append(step.name)
        elapsed = (time.monotonic() - t0) * 1000
        state.meta[f"step_ms.{step.name}"] = round(elapsed, 2)

    return state


async def run_all_phases(state: ContextState) -> ContextState:
    """Run all phases in order. This is the main entry point."""
    t0 = time.monotonic()
    for phase in PHASE_ORDER:
        state = await run_phase(phase, state)
    state.build_ms = round((time.monotonic() - t0) * 1000, 2)
    return state
