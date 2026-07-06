-- H1 — Work queue (team work items)
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

CREATE TABLE IF NOT EXISTS work_item_counters (
    tenant_id TEXT PRIMARY KEY,
    next_seq  INT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS work_items (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    priority        TEXT NOT NULL DEFAULT 'normal',
    assignee_id     UUID,
    reporter_id     UUID NOT NULL,
    workspace_path  TEXT,
    repo            TEXT,
    session_id      TEXT,
    approval_ids    JSONB NOT NULL DEFAULT '[]'::jsonb,
    labels          TEXT[] NOT NULL DEFAULT '{}',
    source          TEXT NOT NULL DEFAULT 'manual',
    external_url    TEXT,
    external_id     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS work_items_tenant_status_idx
    ON work_items (tenant_id, status, updated_at DESC);
