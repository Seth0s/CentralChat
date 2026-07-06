# Central orchestrator — default SYSTEM (bundled)

This file is the **versioned bundled base** for the orchestrator-wide SYSTEM role.
**Fase 11** will load it into the LLM pipeline with the precedence documented in
`docs/ADR-014-system-prompt-versioning.md` (L6 policy → bundled → optional overlay → user prefs → history).

Operational overlay (optional): `state/system_prompt.md` under `CENTRAL_ROOT`, or override via
`CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH`.

Do not put secrets here. Keep content suitable for all tenants unless a future ADR introduces per-tenant bundles.
