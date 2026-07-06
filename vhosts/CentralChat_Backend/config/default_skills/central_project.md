# Central Project

Central is a hybrid VPS+PC AI assistant platform. Here's how it works:

## Architecture

- **VPS (Brain):** Runs the orchestrator. Manages memory, context, RAG,
  approvals, and coordinates sessions.
- **PC (Muscles):** Runs the connector. Executes shell commands, reads/writes
  files, and streams inference results.
- **Postgres:** Single source of truth for state, sessions, memory, quotas.

## Key directories

- `orchestrator/app/` — Domain files (1 file = 1 domain)
- `orchestrator/app/shared/` — Cross-cutting utilities (39 files)
- `connector/` — Client-side agent that runs on the user's machine
- `config/` — Tool definitions, skills, system prompts
- `migrations/` — Raw SQL migration files (run with `scripts/run_migrations.py`)
- `scripts/` — Workers: retention, embedding, backup, context sync

## Key domain files

| File | Domain |
|------|--------|
| `server.py` | Thin FastAPI router (437 lines) |
| `context.py` | Context assembly, compaction, graph |
| `tools.py` | Tool registry, loop, policy |
| `auth.py` | JWT, OIDC, rate limiting |
| `sessions.py` | Chat sessions, preferences, summaries |
| `approvals.py` | HITL approval flow |
| `actions.py` | System action handlers |
| `inference.py` | Model routing, catalog, auto-tier |
| `rag.py` | Document/session/product RAG, memory |
| `connector.py` | Connector registry, jobs, file tools |
| `workspace.py` | Slot graph, canvas, multi-artifact |
| `playbook.py` | Curated playbook recipes |
