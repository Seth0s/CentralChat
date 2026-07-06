-- T5.3 — Additional indexes for tables created in migrations 001–002.
-- Indexes for RAG/memory/session tables live in 017_deferred_indexes.sql.

CREATE INDEX IF NOT EXISTS idx_tenant_config_tenant_id
    ON tenant_config (tenant_id);

CREATE INDEX IF NOT EXISTS idx_tenant_quotas_period_end
    ON tenant_quotas (period_end DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_quotas_unique_period
    ON tenant_quotas (tenant_id, period_start);
