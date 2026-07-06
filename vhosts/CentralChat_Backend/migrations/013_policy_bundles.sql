-- B2.6 — Normalized policy bundles (D-POL-1)
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

CREATE TABLE IF NOT EXISTS policy_bundles (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL,
    version       INT NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    label         TEXT,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, version)
);

CREATE TABLE IF NOT EXISTS policy_repo_rules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id     UUID NOT NULL REFERENCES policy_bundles(id) ON DELETE CASCADE,
    pattern       TEXT NOT NULL,
    read_mode     TEXT,
    write_mode    TEXT,
    approval      TEXT,
    sort_order    INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS policy_tool_rules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id     UUID NOT NULL REFERENCES policy_bundles(id) ON DELETE CASCADE,
    tool          TEXT NOT NULL,
    denied_pattern TEXT NOT NULL,
    sort_order    INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tenant_active_policy (
    tenant_id     TEXT PRIMARY KEY,
    bundle_id     UUID NOT NULL REFERENCES policy_bundles(id),
    activated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_by  TEXT
);

CREATE INDEX IF NOT EXISTS policy_bundles_tenant_status_idx
    ON policy_bundles (tenant_id, status, version DESC);
