-- H1 — Append-only audit log + RBAC roles on auth_users
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

CREATE TABLE IF NOT EXISTS audit_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL,
    user_id       UUID,
    session_id    TEXT,
    approval_id   UUID,
    work_item_id  TEXT,
    action        TEXT NOT NULL,
    resource      TEXT,
    payload_hash  TEXT,
    model         TEXT,
    tokens_in     INT,
    tokens_out    INT,
    client        TEXT,
    ip            INET,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_created_idx
    ON audit_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_action_idx
    ON audit_events (tenant_id, action, created_at DESC);

-- RBAC role on auth_users (viewer | developer | approver | admin | auditor)
ALTER TABLE IF EXISTS auth_users
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'developer';
