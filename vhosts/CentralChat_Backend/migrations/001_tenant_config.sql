-- T1 — tenant_config: configuração por tenant
-- Executar: psql $MEMORY_DB_URL -f migrations/001_tenant_config.sql

CREATE TABLE IF NOT EXISTS tenant_config (
    tenant_id      TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    max_concurrent_streams INT DEFAULT 3,
    rate_limit_per_window     INT DEFAULT 60,
    rate_limit_window_seconds INT DEFAULT 60,
    features_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tenant defaults para o modo single-tenant
INSERT INTO tenant_config (tenant_id, display_name)
    VALUES ('default', 'Default Tenant')
    ON CONFLICT (tenant_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_tenant_config_updated
    ON tenant_config (updated_at DESC);
