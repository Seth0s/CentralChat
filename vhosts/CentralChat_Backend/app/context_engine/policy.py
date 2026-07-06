"""ContextEngine policy — re-exports from app.context_policy.

This is the canonical import path for policy resolution within the
context_engine package. The implementation lives in app/context_policy.py
for now (transition — plan §5 says it belongs here eventually).

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §5
"""

from __future__ import annotations

# Re-export everything from the canonical policy module.
# When policy moves into this package, just flip the imports.
from app.context_policy import (  # noqa: F401
    AutoGate,
    ContextPolicy,
    build_policy_summary_pt,
    resolve_policy,
)

__all__ = [
    "AutoGate",
    "ContextPolicy",
    "build_policy_summary_pt",
    "resolve_policy",
]
